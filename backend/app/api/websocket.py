"""WebSocket API endpoints for real-time updates"""

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Depends, Query

from app.core.http_metrics import record_websocket_event
from typing import Optional, Set
import json
import structlog

from app.services.websocket_manager import websocket_manager
from app.api.auth import resolve_websocket_user
from app.middleware.request_context import correlation_id_from_headers

logger = structlog.get_logger()
router = APIRouter()


@router.websocket("/ws")
async def websocket_endpoint(
    websocket: WebSocket,
    token: Optional[str] = Query(None),
    organization_id: Optional[str] = Query(None),
    asset_ids: Optional[str] = Query(None)  # Comma-separated list
):
    """
    WebSocket endpoint for real-time telemetry, state changes, and alarms.
    
    Query Parameters:
    - token: JWT authentication token
    - organization_id: Organization to subscribe to
    - asset_ids: Optional comma-separated list of asset IDs to filter (empty = all)
    
    Message Types Received from Client:
    - subscribe: Update subscription filters
    - ping: Keep connection alive
    
    Message Types Sent to Client:
    - telemetry: Real-time sensor data
    - state: PackML state transitions
    - alarm: New alarm events
    - command_status: Command execution updates
    - connection_established: Initial connection confirmation
    """
    # Preferred auth transport: the token rides the Sec-WebSocket-Protocol
    # header as ["bearer.v1", "<jwt>"] — query-string tokens end up in access
    # logs and proxies. The ?token= form remains as a legacy fallback.
    negotiated_subprotocol = None
    proto_header = websocket.headers.get("sec-websocket-protocol", "")
    proto_parts = [p.strip() for p in proto_header.split(",") if p.strip()]
    if len(proto_parts) >= 2 and proto_parts[0] == "bearer.v1":
        token = proto_parts[1]
        # Echo the marker protocol back or browsers abort the handshake.
        negotiated_subprotocol = "bearer.v1"

    # FS-108: bind a connection-scoped correlation id so EVERY log line in this
    # WebSocket session carries it. BaseHTTPMiddleware (which binds request_id on
    # the HTTP path) never runs for the WebSocket scope, so WS logs were
    # previously uncorrelatable. Honour an inbound X-Request-ID / traceparent
    # from the handshake so a WS session lines up with the HTTP trace that opened
    # it. Unbound in the finally, mirroring the HTTP middleware.
    connection_id = correlation_id_from_headers(websocket.headers)
    structlog.contextvars.bind_contextvars(request_id=connection_id)
    try:
        await _serve_websocket(
            websocket, token, organization_id, asset_ids, negotiated_subprotocol
        )
    finally:
        structlog.contextvars.unbind_contextvars("request_id")


async def _serve_websocket(
    websocket: WebSocket,
    token: Optional[str],
    organization_id: Optional[str],
    asset_ids: Optional[str],
    negotiated_subprotocol: Optional[str],
):
    # Validate authentication via the shared resolver (handles JWTs and the
    # dev-token bypass under ALLOW_DEV_TOKEN — one ws auth path, not two).
    user = None
    if token:
        try:
            user = await resolve_websocket_user(token)
        except Exception as e:
            await websocket.close(code=1008, reason="Authentication failed")
            logger.warning("websocket_auth_failed", error=str(e))
            return
        if user is None:
            await websocket.close(code=1008, reason="Authentication failed")
            logger.warning("websocket_auth_failed", error="invalid token")
            return

    # Default to user's organization if not specified
    if not organization_id and user:
        organization_id = str(user.organization_id)

    if not organization_id:
        await websocket.close(code=1008, reason="Organization ID required")
        return

    # Connect client
    await websocket_manager.connect_client(websocket, organization_id,
                                           subprotocol=negotiated_subprotocol)
    # Instrumented for FS-229. There were no WebSocket metrics at all, so a
    # "drop rate" alert had nothing to measure — realtime could degrade to zero
    # connected clients with no signal anywhere.
    record_websocket_event("connect", +1)
    
    # Parse asset filter
    subscribed_assets: Set[str] = set()
    if asset_ids:
        subscribed_assets = set(a.strip() for a in asset_ids.split(',') if a.strip())
    
    # Update subscription
    websocket_manager.update_subscription(
        websocket,
        asset_ids=subscribed_assets if subscribed_assets else None,
        message_types={'telemetry', 'state', 'alarm', 'command_status'}
    )
    
    logger.info(
        "websocket_client_connected",
        organization_id=organization_id,
        asset_filter=list(subscribed_assets) if subscribed_assets else "all",
        user_id=str(user.id) if user else "anonymous"
    )

    # Default to the error classification: if we somehow leave this handler
    # without passing through a known branch, that IS an abnormal teardown and
    # should be counted as one rather than flattering the drop-rate metric.
    disconnect_reason = "disconnect_error"

    try:
        while True:
            # Receive messages from client
            data = await websocket.receive_text()
            
            try:
                message = json.loads(data)
                msg_type = message.get('type')
                
                if msg_type == 'ping':
                    await websocket.send_json({'type': 'pong', 'timestamp': message.get('timestamp')})
                
                elif msg_type == 'subscribe':
                    # Update subscription
                    new_assets = message.get('asset_ids')
                    new_types = message.get('message_types')
                    
                    if new_assets is not None:
                        subscribed_assets = set(new_assets)
                    
                    websocket_manager.update_subscription(
                        websocket,
                        asset_ids=subscribed_assets if subscribed_assets else None,
                        message_types=set(new_types) if new_types else None
                    )
                    
                    await websocket.send_json({
                        'type': 'subscription_updated',
                        'payload': {
                            'asset_ids': list(subscribed_assets) if subscribed_assets else [],
                            'message_types': list(new_types) if new_types else ['telemetry', 'state', 'alarm']
                        }
                    })
                
                elif msg_type == 'unsubscribe':
                    # Clear subscription filters (receive all)
                    websocket_manager.update_subscription(
                        websocket,
                        asset_ids=None,
                        message_types=None
                    )
                    await websocket.send_json({'type': 'unsubscribed'})
                
                else:
                    await websocket.send_json({
                        'type': 'error',
                        'payload': {'message': f'Unknown message type: {msg_type}'}
                    })
            
            except json.JSONDecodeError:
                await websocket.send_json({
                    'type': 'error',
                    'payload': {'message': 'Invalid JSON'}
                })
            
            except Exception as e:
                logger.error("websocket_message_handler_error", error=str(e))
                await websocket.send_json({
                    'type': 'error',
                    'payload': {'message': 'Internal error'}
                })
    
    except WebSocketDisconnect:
        logger.info("websocket_client_disconnected", organization_id=organization_id)
        disconnect_reason = "disconnect_clean"

    except Exception as exc:  # noqa: BLE001 — classify, then re-raise
        # A clean client close and a server-side teardown are different signals.
        # Counting both as "disconnect" would make the drop-rate alert useless,
        # since a busy system produces clean closes constantly.
        logger.warning("websocket_closed_with_error", error=str(exc))
        disconnect_reason = "disconnect_error"
        raise

    finally:
        record_websocket_event(disconnect_reason, -1)
        websocket_manager.disconnect_client(websocket, organization_id)
