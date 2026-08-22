"""
Baidu Netdisk Client powered by BaiduPCS protocol and Cookie authentication.
References and builds upon kokojacket/baidu-autosave architecture.
"""

from __future__ import annotations

import asyncio
import logging
import os
import posixpath
import re
import urllib.parse
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# Try importing BaiduPCSApi from baidupcs-py
try:
    from baidupcs_py.baidupcs import BaiduPCSApi
    from baidupcs_py.baidupcs.errors import BaiduPCSError
    HAS_BAIDUPCS = True
except ImportError:
    BaiduPCSApi = None
    BaiduPCSError = Exception
    HAS_BAIDUPCS = False


def parse_and_clean_cookie(raw_input: str) -> Tuple[str, str, str, Dict[str, str]]:
    """
    Parse and clean user Cookie input.
    Accepts:
    1. Full Cookie string: "BAIDUID=...; BDUSS=...; STOKEN=...;"
    2. Key-value: "BDUSS=xxxx" or "BDUSS_BFESS=xxxx"
    3. Raw BDUSS value directly: "xxxx..."
    Returns: (cookie_str, bduss, stoken, cookies_dict)
    """
    if not raw_input:
        return ("", "", "", {})

    raw = raw_input.strip()
    cookies_dict: Dict[str, str] = {}

    if "=" in raw:
        items = raw.split(";")
        for item in items:
            item = item.strip()
            if not item or "=" not in item:
                continue
            k, v = item.split("=", 1)
            cookies_dict[k.strip()] = v.strip().strip('"').strip("'")

    bduss = cookies_dict.get("BDUSS", "")
    if not bduss and "BDUSS_BFESS" in cookies_dict:
        bduss = cookies_dict["BDUSS_BFESS"]
    elif not bduss and "=" not in raw and len(raw) > 20:
        bduss = raw.strip(";").strip('"').strip("'")
        cookies_dict["BDUSS"] = bduss

    if bduss and "%" in bduss:
        try:
            bduss = urllib.parse.unquote(bduss)
            cookies_dict["BDUSS"] = bduss
        except Exception:
            pass

    stoken = cookies_dict.get("STOKEN", "")

    # Ensure BDUSS_BFESS is present
    if bduss and "BDUSS_BFESS" not in cookies_dict:
        cookies_dict["BDUSS_BFESS"] = bduss

    # Build standard Cookie header string
    cookie_str = "; ".join([f"{k}={v}" for k, v in cookies_dict.items()])
    return (cookie_str, bduss, stoken, cookies_dict)


@dataclass
class NetdiskFile:
    fs_id: int
    path: str
    server_filename: str
    size: int
    isdir: bool
    category: int = 0
    server_mtime: int = 0


@dataclass
class NetdiskQuota:
    total: int
    used: int
    free: int

    @property
    def total_gb(self) -> float:
        return round(self.total / (1024**3), 2)

    @property
    def used_gb(self) -> float:
        return round(self.used / (1024**3), 2)

    @property
    def free_gb(self) -> float:
        return round(self.free / (1024**3), 2)


@dataclass
class NetdiskUserInfo:
    baidu_name: str
    netdisk_name: str
    uk: int
    vip_type: int
    avatar_url: str = ""

    @property
    def vip_label(self) -> str:
        if self.vip_type == 2:
            return "SVIP (超级会员)"
        if self.vip_type == 1:
            return "VIP (普通会员)"
        return "普通用户"


class BaiduClient:
    """
    Baidu Netdisk client utilizing BaiduPCSApi with robust error handling.
    """

    def __init__(
        self,
        cookie: str = "",
        bduss: str = "",
        stoken: str = "",
        auth_manager: Any = None,
        fallback_token: str = "",
    ):
        self.cookie_str, self.bduss, self.stoken, self.cookies_dict = parse_and_clean_cookie(cookie or bduss)
        if bduss and not self.bduss:
            _, self.bduss, _, extra_dict = parse_and_clean_cookie(bduss)
            self.cookies_dict.update(extra_dict)
        if stoken and not self.stoken:
            self.stoken = stoken
            self.cookies_dict["STOKEN"] = stoken

        self.auth_manager = auth_manager
        self.fallback_token = fallback_token
        self._pcs_api: Optional[Any] = None
        self._init_pcs_api()

    @property
    def cookie(self) -> str:
        return self.cookie_str

    def _init_pcs_api(self) -> None:
        """Initialize BaiduPCSApi instance."""
        if not HAS_BAIDUPCS or not (self.bduss or self.cookies_dict):
            self._pcs_api = None
            return

        try:
            self._pcs_api = BaiduPCSApi(
                bduss=self.bduss,
                stoken=self.stoken or None,
                cookies=self.cookies_dict or None,
            )
            logger.info("BaiduPCSApi initialized successfully.")
        except Exception as e:
            logger.error("Failed to initialize BaiduPCSApi: %s", e)
            self._pcs_api = None

    def set_cookie(self, raw_input: str) -> None:
        """Update cookie dynamically."""
        self.cookie_str, self.bduss, self.stoken, self.cookies_dict = parse_and_clean_cookie(raw_input)
        self._init_pcs_api()

    def is_configured(self) -> bool:
        """Check if any Cookie or BDUSS is configured."""
        return bool(self.bduss or self.cookies_dict)

    async def get_user_info(self) -> NetdiskUserInfo:
        """Verify cookie and retrieve user information."""
        if not self.is_configured():
            raise ValueError("尚未配置百度网盘 Cookie 或 BDUSS，请先在网页中绑定。")

        return await asyncio.to_thread(self._sync_get_user_info)

    def _sync_get_user_info(self) -> NetdiskUserInfo:
        if self._pcs_api is not None:
            try:
                # 1. Fetch quota to verify connection
                self._pcs_api.quota()

                # 2. Fetch user profile
                name = "百度网盘用户"
                uk = 0
                vip_type = 0

                try:
                    uinfo = self._pcs_api.user_info()
                    if uinfo:
                        name = getattr(uinfo, "user_name", "") or getattr(uinfo, "baidu_name", "") or name
                        uk = getattr(uinfo, "user_id", 0) or 0
                except Exception as e:
                    logger.debug("user_info lookup: %s", e)

                return NetdiskUserInfo(
                    baidu_name=name,
                    netdisk_name=name,
                    uk=uk,
                    vip_type=vip_type,
                    avatar_url="",
                )
            except Exception as e:
                err = str(e)
                logger.warning("BaiduPCSApi get_user_info failed: %s", err)
                if "-6" in err or "errno: -6" in err:
                    raise RuntimeError("Cookie / BDUSS 无效或已过期 (errno=-6)。请在 pan.baidu.com 重新登录并复制最新 Cookie。")
                raise RuntimeError(f"网盘连接失败: {err}")

        raise ValueError("BaiduPCS 引擎未初始化或不可用。")

    async def get_quota(self) -> NetdiskQuota:
        """Fetch storage quota information."""
        return await asyncio.to_thread(self._sync_get_quota)

    def _sync_get_quota(self) -> NetdiskQuota:
        if self._pcs_api is not None:
            try:
                quota = self._pcs_api.quota()
                total = quota[0] if isinstance(quota, (tuple, list)) else getattr(quota, "total", 0)
                used = quota[1] if isinstance(quota, (tuple, list)) else getattr(quota, "used", 0)
                free = max(0, total - used)
                return NetdiskQuota(total=total, used=used, free=free)
            except Exception as e:
                logger.error("BaiduPCSApi get_quota failed: %s", e)
                raise RuntimeError(f"获取网盘空间失败: {e}")

        return NetdiskQuota(total=0, used=0, free=0)

    async def list_dir(
        self,
        dir_path: str = "/",
        order: str = "name",
        desc: int = 0,
        start: int = 0,
        limit: int = 1000,
    ) -> List[NetdiskFile]:
        """List files and folders in directory."""
        return await asyncio.to_thread(self._sync_list_dir, dir_path)

    def _sync_list_dir(self, dir_path: str) -> List[NetdiskFile]:
        clean_dir = "/" + dir_path.strip("/") if dir_path != "/" else "/"
        if self._pcs_api is not None:
            try:
                pcs_files = self._pcs_api.list(clean_dir)
                result = []
                for f in pcs_files:
                    filename = posixpath.basename(f.path) if f.path else getattr(f, "server_filename", "")
                    result.append(
                        NetdiskFile(
                            fs_id=f.fs_id,
                            path=f.path,
                            server_filename=filename,
                            size=getattr(f, "size", 0),
                            isdir=bool(f.is_dir),
                            category=getattr(f, "category", 0),
                            server_mtime=getattr(f, "server_mtime", 0) or getattr(f, "mtime", 0),
                        )
                    )
                logger.info("list_dir for '%s' returned %d items.", clean_dir, len(result))
                return result
            except Exception as e:
                logger.error("BaiduPCSApi list_dir failed for '%s': %s", clean_dir, e)
                raise RuntimeError(f"读取网盘目录 '{clean_dir}' 失败: {e}")

        return []

    async def list_directories(self, dir_path: str = "/") -> List[Dict[str, Any]]:
        """List sub-directories in a specific path for the directory picker."""
        items = await self.list_dir(dir_path=dir_path)
        dirs = []
        for item in items:
            if item.isdir:
                dirs.append(
                    {
                        "fs_id": item.fs_id,
                        "path": item.path,
                        "name": item.server_filename,
                        "mtime": item.server_mtime,
                    }
                )
        return dirs

    async def create_dir(self, dir_path: str) -> Dict[str, Any]:
        """Create single directory on Baidu Netdisk."""
        return await asyncio.to_thread(self._sync_create_dir, dir_path)

    def _sync_create_dir(self, dir_path: str) -> Dict[str, Any]:
        clean_dir = "/" + dir_path.strip("/")
        if self._pcs_api is not None:
            try:
                self._pcs_api.makedir(clean_dir)
                logger.info("Created directory on Baidu Netdisk: %s", clean_dir)
                return {"errno": 0, "path": clean_dir}
            except Exception as e:
                err = str(e)
                if "-8" in err or "already exists" in err:
                    return {"errno": 0, "path": clean_dir}
                logger.error("BaiduPCSApi makedir failed for '%s': %s", clean_dir, e)
                raise RuntimeError(f"创建文件夹 '{clean_dir}' 失败: {e}")

        return {"errno": 0, "path": clean_dir}

    async def ensure_dir(self, dir_path: str) -> None:
        """Recursively ensure a directory exists on Baidu Netdisk."""
        clean_dir = "/" + dir_path.strip("/")
        await asyncio.to_thread(self._sync_create_dir, clean_dir)

    async def rename_file(self, path: str, new_name: str) -> Dict[str, Any]:
        """Rename a file or folder."""
        return await asyncio.to_thread(self._sync_rename_file, path, new_name)

    def _sync_rename_file(self, path: str, new_name: str) -> Dict[str, Any]:
        if self._pcs_api is not None:
            dest_path = posixpath.join(posixpath.dirname(path), new_name)
            try:
                self._pcs_api.rename(path, dest_path)
                return {"errno": 0, "path": dest_path}
            except Exception as e:
                logger.error("BaiduPCSApi rename failed from '%s' to '%s': %s", path, dest_path, e)
                raise RuntimeError(f"重命名失败: {e}")
        return {"errno": 0}

    async def move_file(self, path: str, dest_dir: str, new_name: Optional[str] = None) -> Dict[str, Any]:
        """Move a file or folder to destination directory."""
        return await asyncio.to_thread(self._sync_move_file, path, dest_dir, new_name)

    def _sync_move_file(self, path: str, dest_dir: str, new_name: Optional[str] = None) -> Dict[str, Any]:
        if self._pcs_api is not None:
            clean_dest = "/" + dest_dir.strip("/")
            try:
                self._pcs_api.makedir(clean_dest)
                self._pcs_api.move(path, clean_dest)
                if new_name:
                    dest_file_path = posixpath.join(clean_dest, posixpath.basename(path))
                    final_path = posixpath.join(clean_dest, new_name)
                    self._pcs_api.rename(dest_file_path, final_path)
                return {"errno": 0}
            except Exception as e:
                logger.error("BaiduPCSApi move failed for '%s' to '%s': %s", path, clean_dest, e)
                raise RuntimeError(f"移动文件失败: {e}")
        return {"errno": 0}

    async def batch_move_and_rename(self, move_items: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Execute multiple move and rename operations.
        move_items: [{'path': '/from/old.mkv', 'dest': '/Media/Movies/Movie (2024)', 'newname': 'Movie (2024).mkv'}]
        """
        for item in move_items:
            await self.move_file(
                path=item["path"],
                dest_dir=item["dest"],
                new_name=item.get("newname"),
            )
        return {"errno": 0, "count": len(move_items)}

    async def transfer_share_files(
        self,
        share_url: str,
        share_pwd: str = "",
        target_dir: str = "/Media/Temp",
    ) -> List[Dict[str, Any]]:
        """
        Access shared link and transfer its files into target directory.
        """
        return await asyncio.to_thread(self._sync_transfer_share_files, share_url, share_pwd, target_dir)

    def _sync_transfer_share_files(
        self,
        share_url: str,
        share_pwd: str = "",
        target_dir: str = "/Media/Temp",
    ) -> List[Dict[str, Any]]:
        if self._pcs_api is None:
            raise ValueError("BaiduPCSApi 客户端未就绪。")

        clean_target = "/" + target_dir.strip("/")
        self._pcs_api.makedir(clean_target)

        # 1. Access shared link with password if needed
        if share_pwd:
            try:
                self._pcs_api.access_shared(share_url, password=share_pwd, show_vcode=False)
            except Exception as e:
                logger.warning("access_shared notice: %s", e)

        # 2. Get shared file list
        shared_paths = self._pcs_api.shared_paths(share_url)
        if not shared_paths:
            raise ValueError("该分享链接中没有找到有效的文件或链接已失效。")

        uk = shared_paths[0].uk
        share_id = shared_paths[0].share_id
        bdstoken = shared_paths[0].bdstoken
        fs_ids = [p.fs_id for p in shared_paths]

        # 3. Transfer files to remote directory
        try:
            self._pcs_api.transfer_shared_paths(
                remotedir=clean_target,
                fs_ids=fs_ids,
                uk=uk,
                share_id=share_id,
                bdstoken=bdstoken,
                shared_url=share_url,
            )
            logger.info("Transferred %d shared items to %s", len(fs_ids), clean_target)
        except Exception as e:
            logger.error("transfer_shared_paths error: %s", e)
            raise RuntimeError(f"转存文件失败: {e}")

        transferred = []
        for p in shared_paths:
            filename = posixpath.basename(p.path) if p.path else "file"
            transferred.append(
                {
                    "fs_id": p.fs_id,
                    "server_filename": filename,
                    "target_path": posixpath.join(clean_target, filename),
                    "size": getattr(p, "size", 0),
                    "isdir": bool(p.is_dir),
                }
            )
        return transferred
