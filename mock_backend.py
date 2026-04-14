#!/usr/bin/env python3
"""Minimal mock backend for OmniusGrid dashboard demo"""

import json
import random
import asyncio
from datetime import datetime, timedelta
from uuid import uuid4, UUID
from http.server import HTTPServer, BaseHTTPRequestHandler
import threading
import websockets

# Mock data stores
assets = []
alarms = []
telemetry_data = {}
users = [{"id": "admin", "email": "admin@omniusgrid.local", "role": "admin"}]

def generate_mock_assets():
    """Generate mock manufacturing assets"""
    asset_types = ["3D Printer", "CNC Machine", "Conveyor", "Robot Arm", "Packaging Unit"]
    packml_states = ["Idle", "Executing", "Held", "Suspended", "Aborted", "Complete"]
    
    for i in range(8):
        asset = {
            "id": str(uuid4()),
            "name": f"{random.choice(asset_types)}-{i+1:03d}",
            "asset_type": random.choice(asset_types),
            "current_packml_state": random.choice(packml_states),
            "line": f"Line-{random.randint(1, 3)}",
            "is_active": True,
            "created_at": (datetime.utcnow() - timedelta(days=random.randint(30, 365))).isoformat()
        }
        assets.append(asset)
        
        # Generate telemetry for asset
        telemetry_data[asset["id"]] = {
            "temperature": round(random.uniform(20, 80), 1),
            "pressure": round(random.uniform(1.0, 10.0), 2),
            "speed": round(random.uniform(0, 100), 1),
            "oee": round(random.uniform(60, 95), 1),
            "timestamp": datetime.utcnow().isoformat()
        }

def generate_mock_alarms():
    """Generate mock alarms"""
    severities = ["critical", "major", "minor", "warning"]
    alarm_types = ["Temperature High", "Pressure Low", "Motor Fault", "Network Error", "Maintenance Due"]
    
    for i in range(5):
        alarm = {
            "id": str(uuid4()),
            "asset_id": random.choice(assets)["id"] if assets else str(uuid4()),
            "severity": random.choice(severities),
            "message": random.choice(alarm_types),
            "occurred_at": (datetime.utcnow() - timedelta(hours=random.randint(1, 24))).isoformat(),
            "acknowledged": random.choice([True, False])
        }
        alarms.append(alarm)

generate_mock_assets()
generate_mock_alarms()

class APIHandler(BaseHTTPRequestHandler):
    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, PUT, DELETE, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type, Authorization')
        self.end_headers()
    
    def do_GET(self):
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        
        path = self.path
        response = {}
        
        if path == '/' or path == '/health':
            response = {"status": "healthy", "version": "0.1.0"}
        
        elif '/api/v1/assets' in path:
            if path.endswith('/assets'):
                response = [{**a, "telemetry": telemetry_data.get(a["id"], {})} for a in assets]
            else:
                # Single asset
                asset_id = path.split('/')[-1]
                asset = next((a for a in assets if a["id"] == asset_id), None)
                response = asset or {"error": "Asset not found"}
        
        elif '/api/v1/alarms' in path:
            response = alarms
        
        elif '/api/v1/dashboard/oee' in path:
            response = {
                "fleet_oee": round(sum(t["oee"] for t in telemetry_data.values()) / len(telemetry_data), 1) if telemetry_data else 75.0,
                "total_assets": len(assets),
                "active_assets": len([a for a in assets if a["current_packml_state"] == "Executing"]),
                "critical_alarms": len([a for a in alarms if a["severity"] == "critical" and not a["acknowledged"]])
            }
        
        elif '/api/v1/telemetry/latest' in path:
            asset_id = path.split('/')[-1] if '/latest/' in path else None
            if asset_id and asset_id in telemetry_data:
                response = telemetry_data[asset_id]
            else:
                response = list(telemetry_data.values())[:10]
        
        elif '/api/v1/auth/me' in path:
            response = {"id": "admin", "email": "admin@omniusgrid.local", "role": "admin"}
        
        elif '/api/v1/engines/tactical/status' in path:
            response = {
                "status": "running",
                "model_version": "1.2.3",
                "inference_latency_ms": 45,
                "last_update": datetime.utcnow().isoformat()
            }
        
        elif '/api/v1/engines/strategic/recommendations' in path:
            response = [
                {
                    "id": str(uuid4()),
                    "type": "optimization",
                    "title": "Reduce idle time on Line-1",
                    "description": "Consider rescheduling maintenance to off-peak hours",
                    "confidence": 0.85,
                    "created_at": datetime.utcnow().isoformat()
                }
            ]
        
        else:
            response = {"message": "Mock API endpoint", "path": path}
        
        self.wfile.write(json.dumps(response).encode())
    
    def do_POST(self):
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        
        path = self.path
        
        if '/api/v1/auth/login' in path:
            response = {
                "access_token": "mock-dev-token",
                "token_type": "bearer",
                "user": {"id": "admin", "email": "admin@omniusgrid.local", "role": "admin"}
            }
        elif '/api/v1/alarms' in path and 'acknowledge' in path:
            response = {"success": True, "message": "Alarm acknowledged"}
        else:
            response = {"success": True, "path": path}
        
        self.wfile.write(json.dumps(response).encode())
    
    def log_message(self, format, *args):
        """Suppress request logging"""
        pass

async def websocket_handler(websocket, path):
    """Handle WebSocket connections"""
    try:
        # Send initial connection message
        await websocket.send(json.dumps({
            "type": "connected",
            "timestamp": datetime.utcnow().isoformat()
        }))
        
        # Send periodic updates
        while True:
            await asyncio.sleep(5)
            # Simulate telemetry update
            for asset_id in telemetry_data:
                telemetry_data[asset_id]["temperature"] = round(
                    telemetry_data[asset_id]["temperature"] + random.uniform(-2, 2), 1
                )
                telemetry_data[asset_id]["timestamp"] = datetime.utcnow().isoformat()
            
            await websocket.send(json.dumps({
                "type": "telemetry_update",
                "data": list(telemetry_data.values())[:5],
                "timestamp": datetime.utcnow().isoformat()
            }))
    except websockets.exceptions.ConnectionClosed:
        pass

def run_http_server():
    server = HTTPServer(('localhost', 8000), APIHandler)
    print(f"Mock HTTP API running on http://localhost:8000")
    server.serve_forever()

async def run_websocket_server():
    async with websockets.serve(websocket_handler, 'localhost', 8001):
        print(f"Mock WebSocket running on ws://localhost:8001")
        await asyncio.Future()  # Run forever

if __name__ == '__main__':
    # Start HTTP server in a thread
    http_thread = threading.Thread(target=run_http_server, daemon=True)
    http_thread.start()
    
    # Run WebSocket server in main thread
    print("Starting OmniusGrid Mock Backend...")
    print("API: http://localhost:8000")
    print("WebSocket: ws://localhost:8001")
    print("\nTo connect dashboard, update .env to use port 8001 for WebSocket")
    
    try:
        asyncio.run(run_websocket_server())
    except KeyboardInterrupt:
        print("\nShutting down...")
