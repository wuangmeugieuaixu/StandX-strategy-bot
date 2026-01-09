"""
StandX exchange client implementation.
"""

import os
import asyncio
import json
import time
import base64
import uuid
from decimal import Decimal
from typing import Dict, Any, List, Optional, Tuple
from web3 import Web3
from eth_account.messages import encode_defunct
import websockets
import aiohttp
import nacl.signing
import nacl.encoding
import base58

from .base import BaseExchangeClient, OrderResult, OrderInfo, query_retry
from helpers.logger import TradingLogger


class StandXWebSocketManager:
    """WebSocket manager for StandX market stream and order updates."""

    def __init__(self, jwt_token: str, symbol: str, order_update_callback):
        self.jwt_token = jwt_token
        self.symbol = symbol
        self.order_update_callback = order_update_callback
        self.websocket = None
        self.running = False
        self.ws_url = "wss://perps.standx.com/ws-stream/v1"
        self.logger = None
        self.authenticated = False

    async def connect(self):
        """Connect to StandX WebSocket market stream."""
        retry_count = 0
        max_retries = 5
        
        while retry_count < max_retries:
            try:
                if self.logger:
                    self.logger.log("Connecting to StandX WebSocket", "INFO")
                
                self.websocket = await websockets.connect(self.ws_url)
                self.running = True

                # Authenticate with JWT token
                auth_message = {
                    "auth": {
                        "token": self.jwt_token,
                        "streams": [
                            {"channel": "order"},
                            {"channel": "position"}
                        ]
                    }
                }

                await self.websocket.send(json.dumps(auth_message))
                
                # Wait for auth confirmation
                await asyncio.sleep(1)
                self.authenticated = True
                
                if self.logger:
                    self.logger.log("Authenticated with StandX WebSocket", "INFO")

                # Start listening for messages
                await self._listen()

            except Exception as e:
                retry_count += 1
                if self.logger:
                    self.logger.log(f"WebSocket connection error (attempt {retry_count}/{max_retries}): {e}", "ERROR")
                
                if retry_count < max_retries:
                    await asyncio.sleep(5)
                else:
                    raise

    async def _listen(self):
        """Listen for WebSocket messages."""
        try:
            async for message in self.websocket:
                if not self.running:
                    break

                try:
                    data = json.loads(message)
                    await self._handle_message(data)
                except json.JSONDecodeError as e:
                    if self.logger:
                        self.logger.log(f"Failed to parse WebSocket message: {e}", "ERROR")
                except Exception as e:
                    if self.logger:
                        self.logger.log(f"Error handling WebSocket message: {e}", "ERROR")

        except websockets.exceptions.ConnectionClosed:
            if self.logger:
                self.logger.log("WebSocket connection closed, reconnecting...", "WARNING")
            if self.running:
                await self.connect()
        except Exception as e:
            if self.logger:
                self.logger.log(f"WebSocket listen error: {e}", "ERROR")

    async def _handle_message(self, data: Dict[str, Any]):
        """Handle incoming WebSocket messages."""
        try:
            channel = data.get('channel', '')
            
            if channel == 'order':
                await self._handle_order_update(data.get('data', {}))
            elif channel == 'position':
                # Position updates (if needed in future)
                pass
            elif 'seq' in data and 'auth' in str(data):
                # Auth confirmation
                if self.logger:
                    self.logger.log("WebSocket authentication confirmed", "INFO")

        except Exception as e:
            if self.logger:
                self.logger.log(f"Error handling WebSocket message: {e}", "ERROR")

    async def _handle_order_update(self, order_data: Dict[str, Any]):
        """Handle order update messages."""
        try:
            if self.order_update_callback:
                await self.order_update_callback(order_data)
        except Exception as e:
            if self.logger:
                self.logger.log(f"Error handling order update: {e}", "ERROR")

    async def disconnect(self):
        """Disconnect from WebSocket."""
        self.running = False
        if self.websocket:
            await self.websocket.close()
            if self.logger:
                self.logger.log("WebSocket disconnected", "INFO")

    def set_logger(self, logger):
        """Set the logger instance."""
        self.logger = logger


class StandXAuthManager:
    """Manages authentication for StandX API."""

    def __init__(self, wallet_address: str, private_key: str, chain: str = "bsc"):
        # Initialize Web3 first for address checksumming
        self.w3 = Web3()
        
        # Ensure wallet address is in checksum format (required by StandX)
        self.wallet_address = self.w3.to_checksum_address(wallet_address)
        self.private_key = private_key
        self.chain = chain
        self.base_url = "https://api.standx.com"
        self.jwt_token = None
        
        # Generate ED25519 key pair for request signing
        self.ed25519_signing_key = nacl.signing.SigningKey.generate()
        self.ed25519_public_key = bytes(self.ed25519_signing_key.verify_key)
        self.request_id = base58.b58encode(self.ed25519_public_key).decode()

    async def authenticate(self, logger=None) -> str:
        """Authenticate and get JWT token."""
        if self.jwt_token:
            return self.jwt_token

        try:
            # Step 1: Get signature data
            signed_data_jwt = await self._prepare_signin()
            
            # Step 2: Parse JWT and get message to sign
            payload = self._parse_jwt(signed_data_jwt)
            message = payload.get('message', '')
            
            # Step 3: Sign message with wallet private key
            signature = self._sign_message(message)
            
            # Step 4: Login and get access token
            login_response = await self._login(signature, signed_data_jwt)
            
            # Login response has token directly, not wrapped in success field
            if 'token' not in login_response:
                error_msg = f"Login failed: {login_response}"
                if logger:
                    logger.log(error_msg, "ERROR")
                raise Exception(error_msg)
            
            self.jwt_token = login_response.get('token')
            
            if logger:
                logger.log(f"JWT token obtained successfully", "INFO")
            
            return self.jwt_token
        except Exception as e:
            if logger:
                logger.log(f"Authentication failed: {e}", "ERROR")
            raise

    async def _prepare_signin(self) -> str:
        """Prepare sign-in by requesting signature data."""
        url = f"{self.base_url}/v1/offchain/prepare-signin?chain={self.chain}"
        
        data = {
            "address": self.wallet_address,
            "requestId": self.request_id
        }
        
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=data, headers={"Content-Type": "application/json"}) as response:
                result = await response.json()
                
                if not result.get('success'):
                    raise Exception(f"Failed to prepare signin: {result}")
                
                return result.get('signedData')

    def _parse_jwt(self, token: str) -> Dict[str, Any]:
        """Parse JWT token payload."""
        try:
            parts = token.split('.')
            if len(parts) != 3:
                raise ValueError("Invalid JWT format")
            
            # Decode payload (second part)
            payload_b64 = parts[1]
            # Add padding if needed
            padding = 4 - len(payload_b64) % 4
            if padding != 4:
                payload_b64 += '=' * padding
            
            payload_bytes = base64.urlsafe_b64decode(payload_b64)
            return json.loads(payload_bytes.decode('utf-8'))
        except Exception as e:
            raise ValueError(f"Failed to parse JWT: {e}")

    def _sign_message(self, message: str) -> str:
        """Sign message with wallet private key."""
        # Use Web3 to sign the message with EIP-191 format
        account = self.w3.eth.account.from_key(self.private_key)
        # Encode message for signing (EIP-191)
        signable_message = encode_defunct(text=message)
        signed_message = account.sign_message(signable_message)
        # Return with 0x prefix as required by API
        return '0x' + signed_message.signature.hex()

    async def _login(self, signature: str, signed_data: str, expires_seconds: int = 604800) -> Dict[str, Any]:
        """Login with signature and get JWT token."""
        url = f"{self.base_url}/v1/offchain/login?chain={self.chain}"
        
        data = {
            "signature": signature,
            "signedData": signed_data,
            "expiresSeconds": expires_seconds
        }
        
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=data, headers={"Content-Type": "application/json"}) as response:
                return await response.json()

    def sign_request(self, payload: str) -> Dict[str, str]:
        """Generate request signature headers."""
        version = "v1"
        request_id = str(uuid.uuid4())
        timestamp = int(time.time() * 1000)
        
        # Build message to sign: "{version},{id},{timestamp},{payload}"
        message = f"{version},{request_id},{timestamp},{payload}"
        
        # Sign with ED25519 private key
        message_bytes = message.encode('utf-8')
        signed = self.ed25519_signing_key.sign(message_bytes)
        signature_bytes = signed.signature
        
        # Base64 encode signature
        signature = base64.b64encode(signature_bytes).decode('utf-8')
        
        return {
            "x-request-sign-version": version,
            "x-request-id": request_id,
            "x-request-timestamp": str(timestamp),
            "x-request-signature": signature
        }


class StandXClient(BaseExchangeClient):
    """StandX exchange client implementation."""

    def __init__(self, config: Dict[str, Any]):
        """Initialize StandX client."""
        super().__init__(config)

        # StandX credentials from environment
        self.wallet_address = os.getenv('STANDX_WALLET_ADDRESS')
        self.private_key = os.getenv('STANDX_PRIVATE_KEY')
        self.chain = os.getenv('STANDX_CHAIN', 'bsc')  # Default to BSC
        
        if not self.wallet_address or not self.private_key:
            raise ValueError("STANDX_WALLET_ADDRESS and STANDX_PRIVATE_KEY must be set in environment variables")

        # Initialize auth manager
        self.auth_manager = StandXAuthManager(
            wallet_address=self.wallet_address,
            private_key=self.private_key,
            chain=self.chain
        )
        
        self.api_base_url = "https://perps.standx.com/api"
        self._order_update_handler = None
        self.ws_manager = None
        self.logger = None

    def _validate_config(self) -> None:
        """Validate StandX configuration."""
        required_env_vars = ['STANDX_WALLET_ADDRESS', 'STANDX_PRIVATE_KEY']
        missing_vars = [var for var in required_env_vars if not os.getenv(var)]
        if missing_vars:
            raise ValueError(f"Missing required environment variables: {missing_vars}")

    async def connect(self) -> None:
        """Connect to StandX WebSocket."""
        # Authenticate and get JWT token
        jwt_token = await self.auth_manager.authenticate()
        
        # Initialize WebSocket manager
        self.ws_manager = StandXWebSocketManager(
            jwt_token=jwt_token,
            symbol=self.config.contract_id,
            order_update_callback=self._handle_websocket_order_update
        )
        
        # Initialize logger
        self.logger = TradingLogger(exchange="standx", ticker=self.config.ticker, log_to_console=False)
        self.ws_manager.set_logger(self.logger)

        # Start WebSocket connection in background task
        asyncio.create_task(self.ws_manager.connect())
        
        # Wait for connection and authentication
        await asyncio.sleep(2)

    async def disconnect(self) -> None:
        """Disconnect from StandX."""
        if self.ws_manager:
            await self.ws_manager.disconnect()

    async def _handle_websocket_order_update(self, order_data: Dict[str, Any]):
        """Handle WebSocket order updates."""
        try:
            if not self._order_update_handler:
                return

            order_id = order_data.get('cl_ord_id', '')
            status = order_data.get('status', '')
            
            # Map StandX status to trading_bot expected format (dict)
            if status == 'filled':
                await self._order_update_handler({
                    'contract_id': order_data.get('symbol', ''),
                    'order_id': order_id,
                    'status': 'filled',
                    'side': order_data.get('side', ''),
                    'size': str(order_data.get('qty', '0')),
                    'price': str(order_data.get('fill_avg_price', '0')),
                    'filled_size': str(order_data.get('fill_qty', '0'))
                })
            elif status == 'canceled':
                await self._order_update_handler({
                    'contract_id': order_data.get('symbol', ''),
                    'order_id': order_id,
                    'status': 'canceled',
                    'side': order_data.get('side', ''),
                    'size': str(order_data.get('qty', '0')),
                    'price': str(order_data.get('price', '0')),
                    'filled_size': str(order_data.get('fill_qty', '0'))
                })

        except Exception as e:
            if self.logger:
                self.logger.log(f"Error handling WebSocket order update: {e}", "ERROR")

    async def get_contract_attributes(self) -> Tuple[str, Decimal]:
        """Get contract attributes (symbol and tick size)."""
        # For StandX, use format like "BTC-USD", "ETH-USD"
        symbol = f"{self.config.ticker}-USD"
        
        # Get tick size from symbol info
        url = f"{self.api_base_url}/query_symbol_info"
        
        params = {"symbol": symbol}
        
        async with aiohttp.ClientSession() as session:
            async with session.get(url, params=params) as response:
                if response.status == 200:
                    data = await response.json()
                    # API returns a list, get the first item
                    if isinstance(data, list) and len(data) > 0:
                        symbol_info = data[0]
                        tick_size = Decimal(str(symbol_info.get('tick_size', '0.01')))
                        return symbol, tick_size
                    elif isinstance(data, dict):
                        # Fallback if API returns dict instead
                        tick_size = Decimal(str(data.get('tick_size', '0.01')))
                        return symbol, tick_size
                    else:
                        # Return default if unexpected format
                        return symbol, Decimal('0.01')
                else:
                    # Return default if API call fails
                    return symbol, Decimal('0.01')

    @query_retry(default_return=OrderResult(success=False, error_message="Retry failed"))
    async def place_open_order(self, contract_id: str, quantity: Decimal, direction: str) -> OrderResult:
        """Place an open order (market order)."""
        try:
            jwt_token = await self.auth_manager.authenticate()
            
            # Prepare order payload
            order_data = {
                "symbol": contract_id,
                "side": direction,  # 'buy' or 'sell'
                "order_type": "market",
                "qty": str(quantity),
                "time_in_force": "ioc",  # Immediate or cancel
                "reduce_only": False
            }
            
            payload_str = json.dumps(order_data)
            
            # Generate request signature
            signature_headers = self.auth_manager.sign_request(payload_str)
            
            # Prepare headers
            headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {jwt_token}",
                **signature_headers
            }
            
            # Send order request
            url = f"{self.api_base_url}/new_order"
            
            async with aiohttp.ClientSession() as session:
                async with session.post(url, data=payload_str, headers=headers) as response:
                    result = await response.json()
                    
                    if response.status == 200:
                        # Order accepted (asynchronous processing)
                        return OrderResult(
                            success=True,
                            order_id=result.get('cl_ord_id', ''),
                            side=direction,
                            size=quantity,
                            status='pending'
                        )
                    else:
                        return OrderResult(
                            success=False,
                            error_message=result.get('message', 'Order placement failed')
                        )

        except Exception as e:
            return OrderResult(success=False, error_message=str(e))

    @query_retry(default_return=OrderResult(success=False, error_message="Retry failed"))
    async def place_close_order(self, contract_id: str, quantity: Decimal, price: Decimal, side: str) -> OrderResult:
        """Place a close order (limit order)."""
        try:
            jwt_token = await self.auth_manager.authenticate()
            
            # Prepare order payload
            order_data = {
                "symbol": contract_id,
                "side": side,  # 'buy' or 'sell'
                "order_type": "limit",
                "qty": str(quantity),
                "price": str(self.round_to_tick(price)),
                "time_in_force": "gtc",  # Good till cancel
                "reduce_only": True  # Close order should reduce position
            }
            
            payload_str = json.dumps(order_data)
            
            # Generate request signature
            signature_headers = self.auth_manager.sign_request(payload_str)
            
            # Prepare headers
            headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {jwt_token}",
                **signature_headers
            }
            
            # Send order request
            url = f"{self.api_base_url}/new_order"
            
            async with aiohttp.ClientSession() as session:
                async with session.post(url, data=payload_str, headers=headers) as response:
                    result = await response.json()
                    
                    if response.status == 200:
                        return OrderResult(
                            success=True,
                            order_id=result.get('cl_ord_id', ''),
                            side=side,
                            size=quantity,
                            price=price,
                            status='pending'
                        )
                    else:
                        return OrderResult(
                            success=False,
                            error_message=result.get('message', 'Order placement failed')
                        )

        except Exception as e:
            return OrderResult(success=False, error_message=str(e))

    @query_retry(default_return=OrderResult(success=False, error_message="Retry failed"))
    async def cancel_order(self, order_id: str) -> OrderResult:
        """Cancel an order."""
        try:
            jwt_token = await self.auth_manager.authenticate()
            
            # Prepare cancel payload
            cancel_data = {
                "cl_ord_id": order_id
            }
            
            payload_str = json.dumps(cancel_data)
            
            # Generate request signature
            signature_headers = self.auth_manager.sign_request(payload_str)
            
            # Prepare headers
            headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {jwt_token}",
                **signature_headers
            }
            
            # Send cancel request
            url = f"{self.api_base_url}/cancel_order"
            
            async with aiohttp.ClientSession() as session:
                async with session.post(url, data=payload_str, headers=headers) as response:
                    result = await response.json()
                    
                    if response.status == 200:
                        return OrderResult(success=True, order_id=order_id, status='canceled')
                    else:
                        return OrderResult(
                            success=False,
                            error_message=result.get('message', 'Order cancellation failed')
                        )

        except Exception as e:
            return OrderResult(success=False, error_message=str(e))

    @query_retry(default_return=None)
    async def get_order_info(self, order_id: str) -> Optional[OrderInfo]:
        """Get order information."""
        try:
            jwt_token = await self.auth_manager.authenticate()
            
            headers = {
                "Authorization": f"Bearer {jwt_token}"
            }
            
            url = f"{self.api_base_url}/orders?cl_ord_id={order_id}"
            
            async with aiohttp.ClientSession() as session:
                async with session.get(url, headers=headers) as response:
                    orders = await response.json()
                    
                    if orders and len(orders) > 0:
                        order = orders[0]
                        return OrderInfo(
                            order_id=order.get('cl_ord_id', ''),
                            side=order.get('side', ''),
                            size=Decimal(str(order.get('qty', '0'))),
                            price=Decimal(str(order.get('price', '0'))),
                            status=order.get('status', ''),
                            filled_size=Decimal(str(order.get('fill_qty', '0')))
                        )
            
            return None

        except Exception as e:
            if self.logger:
                self.logger.log(f"Error getting order info: {e}", "ERROR")
            return None

    @query_retry(default_return=[])
    async def get_active_orders(self, contract_id: str) -> List[OrderInfo]:
        """Get active orders for a contract."""
        try:
            jwt_token = await self.auth_manager.authenticate(self.logger)
            
            if not jwt_token:
                if self.logger:
                    self.logger.log("JWT token is None, authentication failed", "ERROR")
                return []
            
            url = f"{self.api_base_url}/query_open_orders"
            
            # Build query parameters
            params = {}
            if contract_id:
                params['symbol'] = contract_id
            
            # Build query string for signing
            query_str = '&'.join([f"{k}={v}" for k, v in sorted(params.items())]) if params else ""
            
            # Generate request signature
            signature_headers = self.auth_manager.sign_request(query_str)
            
            headers = {
                "Authorization": f"Bearer {jwt_token}",
                **signature_headers
            }
            
            if self.logger:
                self.logger.log(f"GET {url} with JWT token (length: {len(jwt_token)})", "DEBUG")
            
            async with aiohttp.ClientSession() as session:
                async with session.get(url, headers=headers, params=params) as response:
                    if response.status != 200:
                        error_text = await response.text()
                        if self.logger:
                            self.logger.log(f"Error getting active orders: HTTP {response.status}, Response: {error_text}", "ERROR")
                        return []
                    
                    data = await response.json()
                    
                    # API may return list directly or wrapped in {"result": [...]}
                    if isinstance(data, list):
                        orders = data
                    else:
                        orders = data.get('result', [])
                    
                    # Handle list of orders
                    if not isinstance(orders, list):
                        if self.logger:
                            self.logger.log(f"Unexpected response format: {type(orders)}", "ERROR")
                        return []
                    
                    active_orders = []
                    for order in orders:
                        # query_open_orders returns only open orders, but check status anyway
                        if order.get('status') in ['open', 'new']:
                            active_orders.append(OrderInfo(
                                order_id=order.get('cl_ord_id', ''),
                                side=order.get('side', ''),
                                size=Decimal(str(order.get('qty', '0'))),
                                price=Decimal(str(order.get('price', '0'))),
                                status=order.get('status', ''),
                                filled_size=Decimal(str(order.get('fill_qty', '0'))),
                                remaining_size=Decimal(str(order.get('qty', '0'))) - Decimal(str(order.get('fill_qty', '0')))
                            ))
                    
                    return active_orders

        except Exception as e:
            if self.logger:
                self.logger.log(f"Error getting active orders: {e}", "ERROR")
            return []

    @query_retry(default_return=Decimal(0))
    async def get_account_positions(self) -> Decimal:
        """Get account positions."""
        try:
            jwt_token = await self.auth_manager.authenticate()
            
            # Add symbol query parameter if we have a contract_id
            params = {}
            if self.config.contract_id:
                params['symbol'] = self.config.contract_id
            
            # Build query string for signing
            query_str = '&'.join([f"{k}={v}" for k, v in sorted(params.items())]) if params else ""
            
            # Generate request signature
            signature_headers = self.auth_manager.sign_request(query_str)
            
            headers = {
                "Authorization": f"Bearer {jwt_token}",
                **signature_headers
            }
            
            url = f"{self.api_base_url}/query_positions"
            
            async with aiohttp.ClientSession() as session:
                async with session.get(url, headers=headers, params=params) as response:
                    if response.status != 200:
                        error_text = await response.text()
                        if self.logger:
                            self.logger.log(f"Error getting account positions: HTTP {response.status}, Response: {error_text}", "ERROR")
                        return Decimal(0)
                    
                    data = await response.json()
                    
                    # API may return list directly or wrapped in {"result": [...]}
                    if isinstance(data, list):
                        positions = data
                    else:
                        positions = data.get('result', [])
                    
                    # Handle list of positions
                    if not isinstance(positions, list):
                        if self.logger:
                            self.logger.log(f"Unexpected response format: {type(positions)}", "ERROR")
                        return Decimal(0)
                    
                    total_position = Decimal(0)
                    for position in positions:
                        if position.get('symbol') == self.config.contract_id:
                            qty = Decimal(str(position.get('qty', '0')))
                            total_position += qty
                    
                    return total_position

        except Exception as e:
            if self.logger:
                self.logger.log(f"Error getting account positions: {e}", "ERROR")
            return Decimal(0)

    def setup_order_update_handler(self, handler) -> None:
        """Setup order update handler for WebSocket."""
        self._order_update_handler = handler

    def get_exchange_name(self) -> str:
        """Get the exchange name."""
        return "standx"
