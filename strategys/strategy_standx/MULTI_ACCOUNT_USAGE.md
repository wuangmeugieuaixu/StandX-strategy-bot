# StandX 多账户使用说明

## 配置多个账户

在 `.env` 文件中设置多个私钥：

```env
# 账户编号为 01
STANDX_PRIVATE_KEY_01=0xee14fff64cdfcb62bcedd60fbb06fefddbef0d2594e6815b1c489e68340b8390

# 账户编号为 02
STANDX_PRIVATE_KEY_02=0xb6eaf82d759a405d973babc74cf52c2d25be7d4da332ca814a34fbcf602b4b4e

# 账户编号为 03
STANDX_PRIVATE_KEY_03=your_private_key_here_03

# 更多账户...
STANDX_PRIVATE_KEY_04=your_private_key_here_04
STANDX_PRIVATE_KEY_05=your_private_key_here_05
```

## 运行指定账户

### 基本用法

```bash
# 使用默认账户 01
python standx_mm.py

# 指定使用账户 02
python standx_mm.py --account 02

# 指定使用账户 03
python standx_mm.py --account 03

# 账户编号可以是一位数，会自动补零
python standx_mm.py --account 5  # 等同于 --account 05
```

### 同时运行多个账户

可以在不同的终端窗口中同时运行多个账户：

```bash
# 终端 1
python standx_mm.py --account 01

# 终端 2
python standx_mm.py --account 02

# 终端 3
python standx_mm.py --account 03
```

## 日志文件区分

每个账户的日志文件会自动包含账户编号，例如：
- 账户 01: `standx_BTC_USD_ACC01_orders.csv`
- 账户 02: `standx_BTC_USD_ACC02_orders.csv`
- 账户 03: `standx_BTC_USD_ACC03_orders.csv`

这样可以方便地区分不同账户的交易记录。

## 错误处理

如果指定的账户私钥未配置或配置错误，程序会显示明确的错误信息：
- 私钥未设置：`请在.env文件中设置 STANDX_PRIVATE_KEY_XX 环境变量`
- 私钥未更换：`请在.env文件中为 STANDX_PRIVATE_KEY_XX 设置真实的私钥`