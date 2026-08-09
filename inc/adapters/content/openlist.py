"""OpenList (openlist.app, Alist 兼容) API SDK client.

Python port of ``inc/adapters/OpenList_API.php`` (Yeraph Studio, GPLv3).
Covers ping, token login (plain / sha256 hash), current user, public
settings and the ``/api/fs`` file operations including stream and form
uploads.

Deviations from the PHP original: ``$_FILES`` upload arrays become
``(path, filename, content)`` arguments, and the framework
``AYA_HTTP_Request`` helper is replaced by ``urllib``. Return
conventions mirror the original: ``False`` on transport-level failure,
``"ERROR:code-message"`` strings for API errors, parsed dicts on
success.

Target Port: unspecified (content capability has no Port yet); kept
import-safe and side-effect free, not bound in the adapter registry.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Sequence
from hashlib import sha256
from typing import Any, cast

__all__ = ["OpenListClient"]

_USER_AGENT = "AIYA-CMS-CLI/1.0"

_FS_API_PATHS = {
    "list": "/api/fs/list",
    "get": "/api/fs/get",
    "dirs": "/api/fs/dirs",
    "search": "/api/fs/search",
    "mkdir": "/api/fs/mkdir",
    "rename": "/api/fs/rename",
    "batch_rename": "/api/fs/batch_rename",
    "regex_rename": "/api/fs/regex_rename",
    "move": "/api/fs/move",
    "recursive_move": "/api/fs/recursive_move",
    "copy": "/api/fs/copy",
    "remove": "/api/fs/remove",
    "remove_empty_directory": "/api/fs/remove_empty_directory",
    "add_offline_download": "/api/fs/add_offline_download",
}

_ApiResult = dict[str, Any] | str | bool


class OpenListClient:
    """OpenList API 客户端（初始化: ``OpenList_API(server, token)``）."""

    def __init__(self, server: str, token: str) -> None:
        self.server = server.rstrip("/")
        self.token = token

    def _request(
        self,
        method: str,
        api: str,
        headers: dict[str, str],
        data: bytes | None = None,
    ) -> tuple[int, str] | None:
        """发送请求；返回 ``(status, body)``，网络失败返回 ``None``."""

        request = urllib.request.Request(
            self.server + api, data=data, headers=headers, method=method
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                return response.status, response.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as exc:
            return exc.code, exc.read().decode("utf-8", errors="replace")
        except urllib.error.URLError:
            return None

    @staticmethod
    def _parse_json(body: str) -> dict[str, Any] | None:
        try:
            data = json.loads(body)
        except json.JSONDecodeError:
            return None
        return data if isinstance(data, dict) else None

    def ping(self) -> bool:
        """Ping 检测；响应 ``pong`` 返回 ``True``."""

        result = self._request("GET", "/ping", {"User-Agent": _USER_AGENT})
        return result is not None and result[0] == 200 and result[1] == "pong"

    def get_token(self, username: str, password: str, otp_code: str | None = None) -> str | bool:
        """获取 token；失败返回 ``"ERROR:message"`` 或 ``False``."""

        headers = {"User-Agent": _USER_AGENT, "Content-Type": "application/json"}
        body = json.dumps(
            {"username": username, "password": password, "otp_code": otp_code},
            ensure_ascii=True,
            separators=(",", ":"),
        ).encode("utf-8")
        result = self._request("POST", "/api/auth/login", headers, body)
        if result is None or result[0] != 200:
            return False
        data = self._parse_json(result[1])
        if data is None:
            return False
        if data.get("code") == 200:
            inner = data.get("data")
            if isinstance(inner, dict):
                return str(inner.get("token") or "")
        return "ERROR:" + str(data.get("message") or "")

    def get_token_hash(
        self, username: str, password: str, otp_code: str | None = None
    ) -> str | bool:
        """获取 token（sha256 hash 密码）；失败返回 ``"ERROR:code-message"`` 或 ``False``."""

        headers = {"User-Agent": _USER_AGENT, "Content-Type": "application/json"}
        hashed = sha256(
            (password + "-https://github.com/alist-org/alist").encode("utf-8")
        ).hexdigest()
        body = json.dumps(
            {"username": username, "password": hashed, "otp_code": otp_code},
            ensure_ascii=True,
            separators=(",", ":"),
        ).encode("utf-8")
        result = self._request("POST", "/api/auth/login/hash", headers, body)
        if result is None or result[0] != 200:
            return False
        data = self._parse_json(result[1])
        if data is None:
            return False
        if data.get("code") == 200:
            inner = data.get("data")
            if isinstance(inner, dict):
                return str(inner.get("token") or "")
        return "ERROR:" + str(data.get("code") or "") + "-" + str(data.get("message") or "")

    def get_me(self) -> _ApiResult:
        """获取当前用户信息."""

        headers = {"User-Agent": _USER_AGENT, "Authorization": self.token}
        result = self._request("GET", "/api/me", headers)
        if result is None or result[0] != 200:
            return False
        data = self._parse_json(result[1])
        if data is None:
            return False
        if data.get("code") == 200:
            return cast(_ApiResult, data.get("data"))
        return "ERROR:" + str(data.get("code") or "") + "-" + str(data.get("message") or "")

    def get_settings(self) -> _ApiResult:
        """获取站点设置（公开接口）."""

        headers = {"User-Agent": _USER_AGENT}
        result = self._request("GET", "/api/public/settings", headers)
        if result is None or result[0] != 200:
            return False
        data = self._parse_json(result[1])
        if data is None:
            return False
        if data.get("code") == 200:
            return cast(_ApiResult, data.get("data"))
        return "ERROR:" + str(data.get("code") or "") + "-" + str(data.get("message") or "")

    def fs_request(
        self, address: str, query_data: dict[str, Any], en_code: bool = True
    ) -> _ApiResult:
        """文件方法：按 ``address`` 路由到对应 ``/api/fs`` 接口."""

        api = _FS_API_PATHS.get(address)
        if api is None:
            return False

        data = None
        if en_code:
            data = json.dumps(query_data, ensure_ascii=True, separators=(",", ":")).encode("utf-8")
        headers = {
            "User-Agent": _USER_AGENT,
            "Content-Type": "application/json",
            "Authorization": self.token,
        }
        result = self._request("POST", api, headers, data)
        if result is None:
            return "ERROR:0-connection failed"
        status, body = result
        if status != 200:
            return f"ERROR:{status}-{body}"
        decoded = self._parse_json(body)
        if decoded is None:
            return f"ERROR:{status}-{body}"
        if decoded.get("code") == 200:
            inner = decoded.get("data")
            if inner is None:
                return str(decoded.get("message") or "")
            return cast(_ApiResult, inner)
        return "ERROR:" + str(decoded.get("code") or "") + "-" + str(decoded.get("message") or "")

    def fs_list(
        self, path: str, password: str = "", page: int = 1, per_page: int = 0, refresh: bool = False
    ) -> _ApiResult:
        """列出文件目录."""

        return self.fs_request(
            "list",
            {
                "path": path,
                "password": password,
                "page": page,
                "per_page": per_page,
                "refresh": refresh,
            },
        )

    def fs_get(
        self, path: str, password: str = "", page: int = 1, per_page: int = 0, refresh: bool = False
    ) -> _ApiResult:
        """获取某个文件/目录信息."""

        return self.fs_request(
            "get",
            {
                "path": path,
                "password": password,
                "page": page,
                "per_page": per_page,
                "refresh": refresh,
            },
        )

    def fs_dir(self, path: str, password: str = "", force_root: bool = False) -> _ApiResult:
        """获取目录."""

        return self.fs_request(
            "dirs", {"path": path, "password": password, "force_root": force_root}
        )

    def fs_search(
        self,
        parent: str,
        keywords: str,
        scope: int = 0,
        page: int = 1,
        per_page: int = 0,
        password: str = "",
    ) -> _ApiResult:
        """搜索文件或文件夹（scope: 0-全部 1-文件夹 2-文件）."""

        return self.fs_request(
            "search",
            {
                "parent": parent,
                "keywords": keywords,
                "scope": scope,
                "page": page,
                "per_page": per_page,
                "password": password,
            },
        )

    def fs_mkdir(self, path: str) -> _ApiResult:
        """新建文件夹."""

        return self.fs_request("mkdir", {"path": path})

    def fs_rename(self, name: str, path: str) -> _ApiResult:
        """重命名文件."""

        return self.fs_request("rename", {"name": name, "path": path})

    def fs_batch_rename(
        self, src: str, src_name: Sequence[str] = (), re_name: Sequence[str] = ()
    ) -> _ApiResult:
        """批量重命名；两个序列长度不一致返回 ``"error"``."""

        if len(src_name) != len(re_name):
            return "error"
        objects = [
            {"src_name": name, "new_name": new_name}
            for name, new_name in zip(src_name, re_name, strict=True)
        ]
        return self.fs_request("batch_rename", {"src_dir": src, "rename_objects": objects})

    def fs_regex_rename(self, src: str, src_regex: str = "", new_regex: str = "") -> _ApiResult:
        """正则重命名."""

        return self.fs_request(
            "regex_rename",
            {"src_dir": src, "src_name_regex": src_regex, "new_name_regex": new_regex},
        )

    def fs_move(self, src: str, dst: str, names: Sequence[str] = ()) -> _ApiResult:
        """移动文件."""

        return self.fs_request("move", {"src_dir": src, "dst_dir": dst, "names": list(names)})

    def fs_move_all(self, src: str, dst: str) -> _ApiResult:
        """聚合移动（移动文件夹内的所有文件）."""

        return self.fs_request("recursive_move", {"src_dir": src, "dst_dir": dst})

    def fs_copy(self, src: str, dst: str, names: Sequence[str] = ()) -> _ApiResult:
        """复制文件."""

        return self.fs_request("copy", {"src_dir": src, "dst_dir": dst, "names": list(names)})

    def fs_remove(self, src: str, names: Sequence[str] = ()) -> _ApiResult:
        """删除文件或文件夹."""

        return self.fs_request("remove", {"names": list(names), "dir": src})

    def fs_remove_empty_dir(self, src: str) -> _ApiResult:
        """删除空文件夹."""

        return self.fs_request("remove_empty_directory", {"src_dir": src})

    def _upload(
        self, api: str, path: str, filename: str, content: bytes, content_type: str
    ) -> _ApiResult:
        """PUT 上传公共逻辑；成功返回 ``data.task``，失败返回 ``False``."""

        headers = {
            "User-Agent": _USER_AGENT,
            "Authorization": self.token,
            "Content-Type": content_type,
            "Content-Length": str(len(content)),
            "File-Path": urllib.parse.quote(path + filename),
            "As-Task": "true",
        }
        result = self._request("PUT", api, headers, content)
        if result is None:
            return False
        data = self._parse_json(result[1])
        if data is None:
            return False
        if data.get("code") == 200:
            inner = data.get("data")
            if isinstance(inner, dict) and "task" in inner:
                return cast(_ApiResult, inner["task"])
        return False

    def fs_from_upload(self, path: str, filename: str, content: bytes) -> _ApiResult:
        """表单上传文件（PUT ``/api/fs/form``，multipart 头 + 原始字节）."""

        return self._upload("/api/fs/form", path, filename, content, "multipart/form-data")

    def fs_upload(self, path: str, filename: str, content: bytes) -> _ApiResult:
        """流式上传文件（PUT ``/api/fs/stream``，octet-stream 原始字节）."""

        return self._upload("/api/fs/stream", path, filename, content, "application/octet-stream")
