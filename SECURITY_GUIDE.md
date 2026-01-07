# 私钥安全配置指南

## ✅ 已完成的安全优化

1. **环境变量配置**: 私钥现在通过 `.env` 文件配置，不再在代码中明文存储
2. **Git 安全**: `.env` 文件已添加到 `.gitignore`，不会被提交到版本控制
3. **示例文件**: 提供 `.env.example` 作为配置模板
4. **依赖管理**: 添加 `python-dotenv` 支持环境变量加载

## 🚀 使用步骤

### 1. 安装依赖
```bash
pip install -r requirements.txt
```

### 2. 配置私钥
```bash
# 复制示例配置文件
cp .env.example .env

# 编辑 .env 文件，填入你的私钥
# STANDX_PRIVATE_KEY=你的私钥
```

### 3. 运行策略
```bash
cd strategys/strategy_standx
python standx_mm.py
```

### 4. 运行测试
```bash
cd exchange/exchange_standx/tests  
python run_trade.py
```

## 🔒 安全特性

- ✅ 私钥存储在本地 `.env` 文件中
- ✅ `.env` 文件不会被 Git 跟踪
- ✅ 代码中不再有硬编码的私钥变量
- ✅ 自动验证私钥是否正确配置
- ✅ 支持带或不带 `0x` 前缀的私钥格式

## ⚠️ 安全提醒

1. **文件权限**: 确保 `.env` 文件只有当前用户可读
   ```bash
   chmod 600 .env
   ```

2. **备份安全**: 备份私钥时使用加密存储

3. **服务器部署**: 生产环境建议使用更安全的密钥管理服务

4. **定期轮换**: 定期更换私钥以降低泄露风险

## 🆘 故障排除

### 错误: "请在.env文件中设置STANDX_PRIVATE_KEY环境变量"

**解决方案**:
1. 确认 `.env` 文件存在于项目根目录
2. 确认文件中包含 `STANDX_PRIVATE_KEY=你的私钥`
3. 确认私钥格式正确（hex格式，64位字符）

### 私钥格式说明

支持以下格式:
- `STANDX_PRIVATE_KEY=1234567890abcdef...` (不带前缀)
- `STANDX_PRIVATE_KEY=0x1234567890abcdef...` (带0x前缀)

## 📁 文件结构

```
StandX-strategy-bot/
├── .env                    # 私钥配置文件 (你需要创建)
├── .env.example           # 配置文件模板
├── .gitignore             # Git 忽略文件 (包含.env)
├── requirements.txt       # 依赖包 (已添加python-dotenv)
└── strategys/
    └── strategy_standx/
        ├── config.yaml    # 策略配置 (已移除私钥字段)
        └── standx_mm.py   # 策略脚本 (已支持环境变量)
```