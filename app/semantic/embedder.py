"""可插拔 embedding 后端（修复方案 -P1-1/P1-2 底座，默认关）。

产品形态拍板：bge-small-zh int8 ONNX、首启下载+缓存、断网降级。当前实现
进度诚实标注：本模块先立"接口 + 可用性探测 + 手动放置模型即生效"，
自动下载器待补——没有校验和的自动下载比手动放置更危险。

开启条件（三者全满足，任一不满足 get_embedder 返回 None → 上层走 BM25）：
1. config features.semantic_embedding = true（缺省关，零行为变化）
2. 模型文件就位：<data_dir>/models/<semantic.model>（默认 bge-small-zh-int8.onnx）
3. onnxruntime + tokenizers 可 import（可选依赖，未装即无）
"""

from __future__ import annotations

import logging
import threading

logger = logging.getLogger("experientia.semantic.embedder")

_LOCK = threading.Lock()
_instance: "OnnxEmbedder | None | bool" = False   # False=未探测, None=不可用


class OnnxEmbedder:
    """bge 系 ONNX 句向量（CLS pooling + L2 归一）。"""

    def __init__(self, model_path, max_len: int = 256):
        import onnxruntime as ort
        from tokenizers import Tokenizer
        from pathlib import Path

        self._tok = Tokenizer.from_file(
            str(Path(model_path).with_suffix(".tokenizer.json")))
        self._tok.enable_truncation(max_len)
        so = ort.SessionOptions()
        so.intra_op_num_threads = 2
        self._sess = ort.InferenceSession(str(model_path), sess_options=so,
                                          providers=["CPUExecutionProvider"])
        self._input = {i.name for i in self._sess.get_inputs()}
        self._cache: dict[str, list[float]] = {}

    def embed(self, texts: list[str]):
        import numpy as np

        todo = [t for t in texts if t not in self._cache]
        if todo:
            enc = self._tok.encode_batch(todo)
            batch = {"input_ids": np.array([e.ids for e in enc]),
                     "attention_mask": np.array([e.attention_mask for e in enc])}
            if "token_type_ids" in self._input:
                batch["token_type_ids"] = np.zeros_like(batch["input_ids"])
            out = self._sess.run(None, batch)[0]          # [B, T, H] CLS 池化
            vecs = out[:, 0, :]
            norms = np.linalg.norm(vecs, axis=1, keepdims=True) + 1e-9
            vecs = vecs / norms
            for t, v in zip(todo, vecs.tolist()):
                if len(self._cache) > 4096:
                    self._cache.clear()
                self._cache[t] = v
        return [self._cache[t] for t in texts]


def get_embedder(store):
    """按开关+文件+依赖三重探测返回单例 embedder，或 None（BM25 降级）。"""
    with _LOCK:
        global _instance
        if _instance is not False:
            return _instance
        try:
            from ..config_schema import feature_enabled

            cfg = store.load_config()
            if not feature_enabled(cfg, "semantic_embedding", default=False):
                return None
            sem = cfg.get("semantic") or {}
            name = str(sem.get("model") or "bge-small-zh-int8.onnx")
            path = store.dir("models") / name
            if not path.exists():
                logger.info("semantic_embedding 开但模型未就位: %s（走 BM25）", path)
                return None
            _instance = OnnxEmbedder(path)
            logger.info("embedding 后端就绪: %s", path.name)
        except ImportError:
            logger.info("onnxruntime/tokenizers 未安装，embedding 不可用（走 BM25）")
            return None
        except Exception as exc:
            logger.warning("embedding 后端初始化失败（走 BM25）: %s", exc)
            _instance = None
        return _instance
