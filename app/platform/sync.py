"""云端同步接口桩（Pro，远期，/ 第三步）。"""


class SyncService:
    def sync(self, *args, **kwargs) -> None:
        raise NotImplementedError("cloud sync is post-v1.0")

    def pull(self, *args, **kwargs) -> None:
        raise NotImplementedError("cloud sync is post-v1.0")
