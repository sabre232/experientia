"""账户接口桩（Team/B2B 方向）。v1.0 无登录、无账户。"""


class AccountService:
    def login(self, *args, **kwargs) -> None:
        raise NotImplementedError("accounts are post-v1.0")

    def logout(self, *args, **kwargs) -> None:
        raise NotImplementedError("accounts are post-v1.0")

    def current(self, *args, **kwargs):
        raise NotImplementedError("accounts are post-v1.0")
