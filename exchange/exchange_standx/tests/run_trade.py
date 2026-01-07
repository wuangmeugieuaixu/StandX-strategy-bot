#!/usr/bin/env python3
"""
StandX 交易脚本
查询余额并下单
"""
import sys
import os
from dotenv import load_dotenv

# 加载.env文件
load_dotenv()

# 添加项目路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from standx_protocol.perps_auth import StandXAuth
from standx_protocol.perp_http import StandXPerpHTTP
from eth_account.messages import encode_defunct
from eth_account import Account
from web3 import Web3

# ==================== 配置区域 ====================
# 钱包私钥从环境变量读取
PRIVATE_KEY = os.getenv('STANDX_PRIVATE_KEY')
if not PRIVATE_KEY:
    raise ValueError("请在.env文件中设置STANDX_PRIVATE_KEY环境变量")

# 交易配置
CHAIN = "bsc"  # 或 "solana"
SYMBOL = "BTC-USD"
SIDE = "buy"  # 或 "sell"
QTY = "0.001"
PRICE = "80000"
# ================================================


def sign_message_with_private_key(private_key: str, message: str) -> str:
    """使用钱包私钥签名消息"""
    # 移除 0x 前缀
    if private_key.startswith('0x'):
        private_key = private_key[2:]
    
    # 创建账户
    account = Account.from_key(private_key)
    
    # 使用 encode_defunct 编码消息（EIP-191 个人签名格式）
    # 这会添加 "\x19Ethereum Signed Message:\n{length}" 前缀
    message_encoded = encode_defunct(text=message)
    
    # 签名消息
    signed = account.sign_message(message_encoded)
    
    # 获取签名的 hex 格式
    # ethers.js 的 signMessage 返回带 0x 前缀的字符串
    signature_hex = signed.signature.hex()
    
    # 确保签名长度正确（应该是 130 个字符，65 字节）
    if len(signature_hex) != 130:
        raise ValueError(f"签名长度不正确: {len(signature_hex)}, 期望 130")
    
    # ethers.js 的 signMessage 返回带 0x 前缀的格式
    # 尝试添加 0x 前缀
    return "0x" + signature_hex


def main():
    """主函数"""
    try:
        print("=" * 60)
        print("StandX 交易脚本")
        print("=" * 60)
        
        # 1. 初始化
        auth = StandXAuth()
        http_client = StandXPerpHTTP()
        
        # 2. 获取钱包地址
        private_key = PRIVATE_KEY
        if private_key.startswith('0x'):
            private_key = private_key[2:]
        
        account = Web3().eth.account.from_key(private_key)
        wallet_address = account.address
        print(f"钱包地址: {wallet_address}")
        
        # 3. 认证
        print("\n步骤 1: 认证...")
        print(f"  RequestId: {auth.request_id}")
        
        def sign_message(msg: str) -> str:
            # 调试：打印完整消息内容
            print(f"  签名消息: {msg}")
            signature = sign_message_with_private_key(PRIVATE_KEY, msg)
            print(f"  签名 (hex): {signature[:66]}... (长度: {len(signature)})")
            return signature
        
        login_response = auth.authenticate(
            chain=CHAIN,
            wallet_address=wallet_address,
            sign_message=sign_message
        )
        
        token = login_response.token
        print(f"✓ 认证成功")
        
        # 4. 查询余额
        print("\n步骤 2: 查询余额...")
        balance = http_client.query_balance(token)
        print(f"✓ 总资产: {balance.get('balance', '0')}")
        print(f"  可用余额: {balance.get('cross_available', '0')}")
        print(f"  账户权益: {balance.get('equity', '0')}")
        
        # 5. 下单
        print(f"\n步骤 3: 下单 {QTY} {SYMBOL} @ {PRICE}...")
        order = http_client.place_order(
            token=token,
            symbol=SYMBOL,
            side=SIDE,
            order_type="limit",
            qty=QTY,
            price=PRICE,
            time_in_force="gtc",
            reduce_only=False,
            auth=auth
        )
        
        if order.get("code") == 0:
            print(f"✓ 下单成功: {order.get('request_id', 'N/A')}")
        else:
            print(f"✗ 下单失败: {order}")
        
        print("\n" + "=" * 60)
        print("完成！")
        print("=" * 60)
        
    except Exception as e:
        print(f"\n✗ 错误: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()
