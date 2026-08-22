"""
Baidu Netdisk OpenAPI (xpan) and Share Operations Client.
"""

from __future__ import annotations

import json
import logging
import posixpath
import urllib.parse
from dataclasses import dataclass
from typing import Any, Dict, List, Optional
import httpx

from .auth import BaiduAuthManager

logger = logging.getLogger(__name__)

XPAN_BASE_URL = "https://pan.baidu.com/rest/2.0/xpan"
PAN_BASE_URL = "https://pan.baidu.com"


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
    """Client for Baidu Netdisk operations."""

    def __init__(
        self,
        auth_manager: BaiduAuthManager,
        fallback_token: str = "",
        bduss: str = "",
        stoken: str = "",
    ):
        self.auth_manager = auth_manager
        self.fallback_token = fallback_token
        self.bduss = bduss
        self.stoken = stoken

    async def _get_access_token(self) -> str:
        token = await self.auth_manager.get_valid_access_token(self.fallback_token)
        if not token:
            raise ValueError(
                "No valid Baidu access_token found. Please authorize with /login first."
            )
        return token

    def _get_cookies(self) -> Dict[str, str]:
        cookies: Dict[str, str] = {}
        if self.bduss:
            cookies["BDUSS"] = self.bduss
        if self.stoken:
            cookies["STOKEN"] = self.stoken
        return cookies

    async def get_user_info(self) -> NetdiskUserInfo:
        """Fetch user basic info."""
        access_token = await self._get_access_token()
        url = f"{XPAN_BASE_URL}/nas"
        params = {"method": "uinfo", "access_token": access_token}

        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(url, params=params)
            data = resp.json()
            if data.get("errno", 0) != 0:
                raise RuntimeError(f"Failed to get user info: {data}")

            return NetdiskUserInfo(
                baidu_name=data.get("baidu_name", ""),
                netdisk_name=data.get("netdisk_name", ""),
                uk=data.get("uk", 0),
                vip_type=data.get("vip_type", 0),
                avatar_url=data.get("avatar_url", ""),
            )

    async def get_quota(self) -> NetdiskQuota:
        """Fetch storage quota information."""
        access_token = await self._get_access_token()
        url = f"{PAN_BASE_URL}/api/quota"
        params = {
            "access_token": access_token,
            "checkexpire": 1,
            "checkfree": 1,
        }

        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(url, params=params)
            data = resp.json()
            if data.get("errno", 0) != 0:
                raise RuntimeError(f"Failed to get quota: {data}")

            total = data.get("total", 0)
            used = data.get("used", 0)
            free = data.get("free", max(0, total - used))
            return NetdiskQuota(total=total, used=used, free=free)

    async def list_dir(
        self,
        dir_path: str = "/",
        order: str = "time",
        desc: int = 1,
        start: int = 0,
        limit: int = 1000,
    ) -> List[NetdiskFile]:
        """List files in directory."""
        access_token = await self._get_access_token()
        url = f"{XPAN_BASE_URL}/file"
        params = {
            "method": "list",
            "access_token": access_token,
            "dir": dir_path,
            "order": order,
            "desc": desc,
            "start": start,
            "limit": limit,
            "web": "web",
        }

        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(url, params=params)
            data = resp.json()
            if data.get("errno", 0) != 0:
                raise RuntimeError(f"Failed to list directory '{dir_path}': {data}")

            files = []
            for item in data.get("list", []):
                files.append(
                    NetdiskFile(
                        fs_id=item["fs_id"],
                        path=item["path"],
                        server_filename=item["server_filename"],
                        size=item.get("size", 0),
                        isdir=bool(item.get("isdir", 0)),
                        category=item.get("category", 0),
                        server_mtime=item.get("server_mtime", 0),
                    )
                )
            return files

    async def list_directories(self, dir_path: str = "/") -> List[Dict[str, Any]]:
        """List sub-directories in a specific path for the directory selector UI."""
        items = await self.list_dir(dir_path=dir_path, order="name", desc=0)
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
        """Create directory on Baidu Netdisk."""
        access_token = await self._get_access_token()
        url = f"{XPAN_BASE_URL}/file"
        params = {
            "method": "create",
            "access_token": access_token,
        }
        data = {
            "path": dir_path,
            "size": 0,
            "isdir": 1,
            "block_list": json.dumps([]),
            "autoinit": 1,
            "rtype": 1,  # 1 = skip/override if exists
        }

        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(url, params=params, data=data)
            res = resp.json()
            # errno == 0 or -8 (already exists)
            if res.get("errno") not in (0, -8, None):
                logger.warning("Create dir response: %s", res)
            return res

    async def ensure_dir(self, dir_path: str) -> None:
        """Recursively ensure a directory exists on Baidu Netdisk."""
        parts = [p for p in dir_path.strip("/").split("/") if p]
        current = ""
        for p in parts:
            current = f"{current}/{p}"
            await self.create_dir(current)

    async def filemanager(self, opera: str, filelist: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Execute filemanager operations:
        opera: 'rename', 'move', 'copy', 'delete'
        """
        access_token = await self._get_access_token()
        url = f"{XPAN_BASE_URL}/file"
        params = {
            "method": "filemanager",
            "access_token": access_token,
            "opera": opera,
        }
        data = {
            "async": 0,
            "filelist": json.dumps(filelist, ensure_ascii=False),
        }

        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(url, params=params, data=data)
            res = resp.json()
            if res.get("errno", 0) != 0:
                logger.error("Filemanager %s failed: %s", opera, res)
                raise RuntimeError(f"Filemanager {opera} failed (errno={res.get('errno')}): {res}")
            return res

    async def rename_file(self, path: str, new_name: str) -> Dict[str, Any]:
        """Rename a file or folder."""
        filelist = [{"path": path, "newname": new_name}]
        return await self.filemanager("rename", filelist)

    async def move_file(self, path: str, dest_dir: str, new_name: Optional[str] = None) -> Dict[str, Any]:
        """Move a file or folder to destination directory."""
        item: Dict[str, Any] = {"path": path, "dest": dest_dir}
        if new_name:
            item["newname"] = new_name
        return await self.filemanager("move", [item])

    async def batch_move_and_rename(self, move_items: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Batch move and rename files.
        move_items: [{"path": "/old/path/file.mp4", "dest": "/Media/Movies/Movie", "newname": "file_clean.mp4"}]
        """
        if not move_items:
            return {"errno": 0}
        return await self.filemanager("move", move_items)

    async def delete_file(self, path: str) -> Dict[str, Any]:
        """Delete a file or folder."""
        return await self.filemanager("delete", [path])

    # --------------------------------------------------------------------------
    # Share Link Transfer
    # --------------------------------------------------------------------------

    async def get_share_info(self, surl: str, pwd: str = "") -> Dict[str, Any]:
        """
        Verify and get file info from a Baidu share link.
        """
        clean_surl = surl.lstrip("1")
        cookies = self._get_cookies()
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            ),
            "Referer": f"https://pan.baidu.com/s/1{clean_surl}",
        }

        async with httpx.AsyncClient(timeout=20.0, headers=headers, cookies=cookies) as client:
            # 1. Verify pwd if provided
            if pwd:
                verify_url = "https://pan.baidu.com/share/verify"
                verify_data = {
                    "surl": clean_surl,
                    "pwd": pwd,
                }
                verify_resp = await client.post(verify_url, data=verify_data)
                verify_res = verify_resp.json()
                if verify_res.get("errno", 0) != 0:
                    raise ValueError(f"Share password verification failed: {verify_res}")
                # Update cookies with returned bdclnd / randadd
                for k, v in verify_resp.cookies.items():
                    cookies[k] = v

            # 2. Get share page or share list
            list_url = f"https://pan.baidu.com/share/list?shorturl={clean_surl}&root=1&page=1&num=100"
            resp = await client.get(list_url, cookies=cookies)
            data = resp.json()
            if data.get("errno", 0) != 0:
                raise RuntimeError(f"Failed to fetch share list (errno={data.get('errno')}): {data}")

            return {
                "surl": clean_surl,
                "share_id": data.get("share_id"),
                "uk": data.get("uk"),
                "file_list": data.get("list", []),
                "title": data.get("title", ""),
            }

    async def transfer_share_files(
        self,
        share_id: int,
        from_uk: int,
        fs_id_list: List[int],
        dest_dir: str = "/",
        pwd: str = "",
    ) -> Dict[str, Any]:
        """
        Transfer files from a verified share to target netdisk folder.
        """
        cookies = self._get_cookies()
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            ),
            "Referer": "https://pan.baidu.com/disk/home",
        }

        # Ensure destination directory exists
        await self.ensure_dir(dest_dir)

        transfer_url = "https://pan.baidu.com/share/transfer"
        params = {
            "shareid": share_id,
            "from": from_uk,
        }
        data = {
            "fsidlist": json.dumps(fs_id_list),
            "path": dest_dir,
        }

        async with httpx.AsyncClient(timeout=30.0, headers=headers, cookies=cookies) as client:
            resp = await client.post(transfer_url, params=params, data=data)
            res = resp.json()
            errno = res.get("errno", 0)
            if errno != 0:
                error_msg = {
                    -6: "Cookie / Token expired or invalid. Please check BDUSS/Login.",
                    2: "Parameters error.",
                    12: "Netdisk space is full.",
                    4: "File already exists in destination directory.",
                    -33: "Share link transfer limit reached.",
                }.get(errno, f"Transfer failed with errno: {errno}")
                raise RuntimeError(f"{error_msg} (raw: {res})")
            return res
