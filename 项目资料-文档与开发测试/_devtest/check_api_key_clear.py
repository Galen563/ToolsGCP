"""验证：API Key 清空必须真的落盘，且不会被旧单槽迁移"还魂"。
用临时目录当数据根 + TOOLSGCP_NO_SETTINGS_WRITE 不设（要真落盘）。"""
import json, os, shutil, sys
sys.path[:0] = [os.path.join('.ToolsGCP'), os.path.join('.ToolsGCP', 'modules')]
tmp = os.path.abspath(os.path.join(".","_devtmp_keytest"))
shutil.rmtree(tmp, ignore_errors=True); os.makedirs(tmp)
from pymodels.core.settings_manager import SettingsManager
m = SettingsManager(config_dir=tmp)
def cfg():
    with open(os.path.join(tmp, "toolsgcp_config.json"), encoding="utf-8") as f:
        return json.load(f)

m.set_api_key("sk-test-abcdef", "deepseek")
assert m.get_api_key("deepseek") == "sk-test-abcdef", m.get_api_key("deepseek")
print("1) 写入后读回 OK")

m.set_api_key("", "deepseek")
print("   清空后读回 =", repr(m.get_api_key("deepseek")))
assert m.get_api_key("deepseek") == "", "清空失败！"
c = cfg()
assert not c.get("api_key_enc_deepseek"), "槽仍残留: %r" % (c.get("api_key_enc_deepseek"),)
print("2) 清空后落盘为空 OK；配置文件键 =", [k for k in c if k.startswith("api_key")])

# 旧单槽场景：配置里只有 legacy 密文
m2 = SettingsManager(config_dir=tmp)
m2.settings["api_key_enc"] = "plain:" + __import__("base64").b64encode(b"LEGACYKEY").decode()
m2.settings.pop("api_key_enc_deepseek", None)
m2.save_settings(m2.settings)
assert m2.get_api_key("deepseek") == "LEGACYKEY", "旧槽迁移应生效"
print("3) 旧单槽迁移读回 OK")
m2.set_api_key("", "deepseek")
assert m2.get_api_key("deepseek") == "", "清空后旧槽又还魂了！"
assert m2.get_api_key("deepseek") == "", "二次读取还不空"
print("4) 清空后旧槽不再还魂 OK")
print("ALL PASS")
