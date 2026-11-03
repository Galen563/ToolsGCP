"""GCP-AI 的请求线程：把"组装上下文 → 发请求 → 解析结果"放进 QThread。

    worker = AIChatWorker(messages, api_key, model, api_base, max_tokens)
    worker.succeeded.connect(on_reply)   # 参数是回答正文
    worker.failed.connect(on_error)      # 参数是"给用户看的说明"

⚠️ run() 里不要碰任何界面控件：界面只能在主线程操作，这里只发信号。
"""

from PyQt5.QtCore import QThread, pyqtSignal

from . import client


class AIChatWorker(QThread):
    """后台跑一次 chat/completions 请求

    succeeded(str) 参数是回答正文；failed(str) 参数是整理好的用户可读说明。
    完整结果（含错误 kind）在 self.result 里。
    """

    succeeded = pyqtSignal(str)
    failed = pyqtSignal(str)

    def __init__(self, messages: list, api_key: str, model: str,
                 api_base: str = "", max_tokens: int = 0,
                 temperature: float = 0.7, parent=None):
        super().__init__(parent)
        self.messages = messages
        self.api_key = api_key
        self.model = model
        self.api_base = api_base
        self.max_tokens = max_tokens
        self.temperature = temperature
        # 调用结束后的完整结果（ChatResult），界面可读它拿 kind
        self.result = None
        # 标记：窗口关了 / 用户点了停止，就别再发信号去打一个已经没了的界面
        self._cancelled = False

    def cancel(self):
        """请求作废（关抽屉时调用）

        ⚠️ urllib 的阻塞读取没法真正中断，这里只是"不再上报结果"；线程会随超时自然结束。
        """
        self._cancelled = True

    def run(self):
        try:
            result = client.chat(
                self.messages, self.api_key, self.model, self.api_base,
                max_tokens=self.max_tokens, temperature=self.temperature)
        except Exception as exc:
            # 万一 client.chat 漏抛异常，也不能让线程带着崩溃退出
            result = client.ChatResult(False, kind=client.KIND_UNKNOWN,
                                       message=f"请求异常：{exc}")
        self.result = result

        if self._cancelled:
            return

        if result.ok:
            self.succeeded.emit(result.content)
        else:
            self.failed.emit(result.message or "请求失败")
