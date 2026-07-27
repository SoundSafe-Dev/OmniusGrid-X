"""WebSocket API endpoints for real-time updates"""

import asyncio
import json
from typing import Optional, Set

import structlog
from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect

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
    - token: Required JWT authentication token
    - organization_id: Optional organization assertion; must match the user
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
    if not token:
        await websocket.close(code=1008, reason="Authentication required")
        return

    try:
        user = await resolve_websocket_user(token)
    except Exception as exc:
        await websocket.close(code=1008, reason="Authentication failed")
        logger.warning(
            "websocket_auth_failed",
            error_type=type(exc).__name__,
        )
        return
    if user is None:
        await websocket.close(code=1008, reason="Authentication failed")
        return
    if user.organization_id is None:
        await websocket.close(code=1008, reason="Organization required")
        return

    authenticated_org_id = str(user.organization_id)
    if organization_id and organization_id != authenticated_org_id:
        await websocket.close(code=1008, reason="Organization mismatch")
        return
    organization_id = authenticated_org_id

    # Connect client
    await websocket_manager.connect_client(websocket, organization_id,
                                           subprotocol=negotiated_subprotocol)
    
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
    
    try:
        while True:
            # Receive messages from client
            try:
                data = await asyncio.wait_for(
                    websocket.receive_text(),
                    timeout=30,
                )
            except asyncio.TimeoutError:
                # Re-read durable account/session state so role changes and
                # deactivation close passive sockets on every API replica.
                if await resolve_websocket_user(token) is None:
                    await websocket.close(
                        code=1008,
                        reason="Authentication expired",
                    )
                    return
                continue
            
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
    
    finally:
        websocket_manager.disconnect_client(websocket, organization_id)
