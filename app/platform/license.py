"""授权检查接口桩（BUSL 商业授权路径）。v1.0 全功能开放，无检查。"""


class LicenseService:
    def check_entitlement(self, *args, **kwargs) -> bool:
        raise NotImplementedError("license gating is post-v1.0")
