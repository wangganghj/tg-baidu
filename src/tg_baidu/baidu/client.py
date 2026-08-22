"""
Baidu Netdisk OpenAPI (xpan) and Cookie/BDUSS Operations Client.
"""

from __future__ import annotations

import json
import logging
import posixpath
import re
import urllib.parse
from dataclasses import dataclass
from typing import Any, Dict, List, Optional
import httpx

from .auth import BaiduAuthManager

logger = logging.getLogger(__name__)

XPAN_BASE_URL = "https://pan.baidu.com/rest/2.0/xpan"
PAN_BASE_URL = "https://pan.baidu.com"


def clean_bduss_string(value: str) -> str:
    """Clean BDUSS string copied from browser DevTools, headers, or storage."""
    if not value:
        return ""
    val = value.strip().strip('"').strip("'")
    if "BDUSS=" in val:
        m = re.search(r"(?:^|;\s*)BDUSS=([^;]+)", val)
        if m:
            val = m.group(1).strip()
    elif "BDUSS_BFESS=" in val:
        m = re.search(r"(?:^|;\s*)BDUSS_BFESS=([^;]+)", val)
        if m:
            val = m.group(1).strip()
    val = val.strip(";").strip('"').strip("'").strip()
    try:
        if "%" in val:
            val = urllib.parse.unquote(val)
    except Exception:
        pass
    return val


def extract_stoken_from_cookie(value: str) -> str:
    """Extract STOKEN if user pasted full Cookie string."""
    if not value:
        return ""
    m = re.search(r"(?:^|;\s*)STOKEN=([^;]+)", value)
    if m:
        return m.group(1).strip().strip(";").strip('"').strip("'")
    return ""


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
    """Client for Baidu Netdisk operations supporting both OAuth Access Token and BDUSS Cookie."""

    def __init__(
        self,
        auth_manager: BaiduAuthManager,
        fallback_token: str = "",
        bduss: str = "",
        stoken: str = "",
    ):
        self.auth_manager = auth_manager
        self.fallback_token = fallback_token
        self.bduss = clean_bduss_string(bduss)
        self.stoken = stoken.strip()

    async def _get_access_token(self) -> Optional[str]:
        """Get valid OAuth access token if available."""
        token = await self.auth_manager.get_valid_access_token(self.fallback_token)
        if token and token != "BDUSS_AUTH_MODE":
            return token
        return None

    def _get_headers(self) -> Dict[str, str]:
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
            ),
            "Referer": "https://pan.baidu.com/disk/main",
            "Origin": "https://pan.baidu.com",
            "Accept": "application/json, text/plain, */*",
        }
        cookie_parts = []
        if self.bduss:
            clean_val = clean_bduss_string(self.bduss)
            cookie_parts.append(f"BDUSS={clean_val}")
            cookie_parts.append(f"BDUSS_BFESS={clean_val}")
        if self.stoken:
            cookie_parts.append(f"STOKEN={self.stoken.strip()}")
        if cookie_parts:
            headers["Cookie"] = "; ".join(cookie_parts)
        return headers

    async def get_user_info(self) -> NetdiskUserInfo:
        """Fetch user basic info via OAuth Token or BDUSS Cookie."""
        access_token = await self._get_access_token()
        headers = self._get_headers()

        # 1. Try OAuth xpan endpoint if token is present
        if access_token:
            url = f"{XPAN_BASE_URL}/nas"
            params = {"method": "uinfo", "access_token": access_token}
            try:
                async with httpx.AsyncClient(timeout=15.0, headers=headers, follow_redirects=True) as client:
                    resp = await client.get(url, params=params)
                    data = resp.json()
                    if data.get("errno", 0) == 0:
                        return NetdiskUserInfo(
                            baidu_name=data.get("baidu_name", ""),
                            netdisk_name=data.get("netdisk_name", ""),
                            uk=data.get("uk", 0),
                            vip_type=data.get("vip_type", 0),
                            avatar_url=data.get("avatar_url", ""),
                        )
            except Exception as e:
                logger.warning("OAuth get_user_info failed, checking BDUSS: %s", e)

        # 2. Try Cookie BDUSS Web endpoints
        if self.bduss:
            async with httpx.AsyncClient(timeout=15.0, headers=headers, follow_redirects=True) as client:
                # A. Try gettemplateuser
                try:
                    resp = await client.get("https://pan.baidu.com/api/gettemplateuser?web=1")
                    if resp.status_code == 200:
                        data = resp.json()
                        if data.get("errno", 0) == 0:
                            records = data.get("records", [])
                            if records:
                                rec = records[0]
                                return NetdiskUserInfo(
                                    baidu_name=rec.get("uname", "百度网盘用户"),
                                    netdisk_name=rec.get("uname", "百度网盘用户"),
                                    uk=rec.get("uk", 0),
                                    vip_type=rec.get("vip_type", 0),
                                    avatar_url=rec.get("avatar_url", ""),
                                )
                            if "userinfo" in data:
                                u = data["userinfo"]
                                return NetdiskUserInfo(
                                    baidu_name=u.get("uname", "百度网盘用户"),
                                    netdisk_name=u.get("uname", "百度网盘用户"),
                                    uk=u.get("uk", 0),
                                    vip_type=u.get("vip_type", 0),
                                    avatar_url=u.get("avatar_url", ""),
                                )
                except Exception as e:
                    logger.debug("gettemplateuser failed: %s", e)

                # B. Try userinfo
                try:
                    resp = await client.get("https://pan.baidu.com/api/userinfo")
                    if resp.status_code == 200:
                        data = resp.json()
                        if data.get("errno", 0) == 0:
                            return NetdiskUserInfo(
                                baidu_name=data.get("username") or data.get("baidu_name", "百度网盘用户"),
                                netdisk_name=data.get("username", "百度网盘用户"),
                                uk=data.get("uk", 0),
                                vip_type=data.get("vip_type", 0),
                                avatar_url=data.get("avatar_url", ""),
                            )
                except Exception as e:
                    logger.debug("userinfo failed: %s", e)

                # C. Try quota check (most reliable validator for BDUSS)
                try:
                    resp = await client.get("https://pan.baidu.com/api/quota?checkexpire=1&checkfree=1")
                    if resp.status_code == 200:
                        data = resp.json()
                        if data.get("errno", 0) == 0:
                            return NetdiskUserInfo(
                                baidu_name="百度网盘用户 (BDUSS 模式)",
                                netdisk_name="BDUSS 已连接",
                                uk=0,
                                vip_type=0,
                                avatar_url="",
                            )
                        elif data.get("errno") == -6:
                            raise RuntimeError("BDUSS Cookie 无效或已过期 (errno=-6)。请确保当前浏览器已登录百度网盘并重新复制 BDUSS。")
                        else:
                            raise RuntimeError(f"BDUSS 验证失败 (errno={data.get('errno')}): {data}")
                except Exception as e:
                    raise RuntimeError(f"{e}")

        raise ValueError("未检测到有效的百度 Access Token 或 BDUSS Cookie。请先登录绑定。")

    async def get_quota(self) -> NetdiskQuota:
        """Fetch storage quota information."""
        access_token = await self._get_access_token()
        headers = self._get_headers()

        url = f"{PAN_BASE_URL}/api/quota"
        params: Dict[str, Any] = {"checkexpire": 1, "checkfree": 1}
        if access_token:
            params["access_token"] = access_token

        async with httpx.AsyncClient(timeout=15.0, headers=headers, follow_redirects=True) as client:
            resp = await client.get(url, params=params)
            data = resp.json()
            if data.get("errno", 0) != 0:
                raise RuntimeError(f"获取网盘容量失败 (errno={data.get('errno')}): {data}")

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
        """List files in directory using Token or BDUSS."""
        access_token = await self._get_access_token()
        headers = self._get_headers()

        url = f"{XPAN_BASE_URL}/file"
        params: Dict[str, Any] = {
            "method": "list",
            "dir": dir_path,
            "order": order,
            "desc": desc,
            "start": start,
            "limit": limit,
            "web": "web",
        }
        if access_token:
            params["access_token"] = access_token

        async with httpx.AsyncClient(timeout=15.0, headers=headers, follow_redirects=True) as client:
            resp = await client.get(url, params=params)
            data = resp.json()
            if data.get("errno", 0) != 0:
                # Fallback to web list api if xpan returns error in BDUSS mode
                if self.bduss and not access_token:
                    web_list_url = f"{PAN_BASE_URL}/api/list"
                    web_params = {
                        "dir": dir_path,
                        "order": order,
                        "desc": desc,
                        "start": start,
                        "num": limit,
                    }
                    web_resp = await client.get(web_list_url, params=web_params)
                    web_data = web_resp.json()
                    if web_data.get("errno", 0) == 0:
                        data = web_data

            if data.get("errno", 0) != 0:
                raise RuntimeError(f"获取目录 '{dir_path}' 失败 (errno={data.get('errno')}): {data}")

            files = []
            for item in data.get("list", []):
                files.append(
                    NetdiskFile(
                        fs_id=item.get("fs_id", 0),
                        path=item.get("path", ""),
                        server_filename=item.get("server_filename", ""),
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
        headers = self._get_headers()

        url = f"{XPAN_BASE_URL}/file"
        params: Dict[str, Any] = {"method": "create"}
        if access_token:
            params["access_token"] = access_token

        data = {
            "path": dir_path,
            "size": 0,
            "isdir": 1,
            "block_list": json.dumps([]),
            "autoinit": 1,
            "rtype": 1,  # 1 = skip/override if exists
        }

        async with httpx.AsyncClient(timeout=15.0, headers=headers, follow_redirects=True) as client:
            resp = await client.post(url, params=params, data=data)
            res = resp.json()
            # errno == 0 or -8 (already exists)
            if res.get("errno") not in (0, -8, None):
                # Fallback to web create
                if self.bduss and not access_token:
                    web_url = f"{PAN_BASE_URL}/api/create"
                    web_resp = await client.post(web_url, data=data)
                    res = web_resp.json()
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
        headers = self._get_headers()

        url = f"{XPAN_BASE_URL}/file"
        params: Dict[str, Any] = {
            "method": "filemanager",
            "opera": opera,
        }
        if access_token:
            params["access_token"] = access_token

        data = {
            "async": 0,
            "filelist": json.dumps(filelist, ensure_ascii=False),
        }

        async with httpx.AsyncClient(timeout=30.0, headers=headers, follow_redirects=True) as client:
            resp = await client.post(url, params=params, data=data)
            res = resp.json()
            if res.get("errno", 0) != 0 and self.bduss and not access_token:
                # Fallback to web api filemanager
                web_url = f"{PAN_BASE_URL}/api/filemanager"
                web_resp = await client.post(web_url, params={"opera": opera}, data=data)
                res = web_resp.json()

            if res.get("errno", 0) != 0:
                logger.error("Filemanager %s failed: %s", opera, res)
                raise RuntimeError(f"文件操作 {opera} 失败 (errno={res.get('errno')}): {res}")
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
        headers = self._get_headers()
        headers["Referer"] = f"https://pan.baidu.com/s/1{clean_surl}"

        async with httpx.AsyncClient(timeout=20.0, headers=headers, follow_redirects=True) as client:
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
                    raise ValueError(f"分享提取码错误或失效: {verify_res}")
                # Update cookies with returned bdclnd / randadd
                cookie_extras = []
                for k, v in verify_resp.cookies.items():
                    cookie_extras.append(f"{k}={v}")
                if cookie_extras and "Cookie" in headers:
                    headers["Cookie"] += "; " + "; ".join(cookie_extras)

            # 2. Get share page or share list
            list_url = f"https://pan.baidu.com/share/list?shorturl={clean_surl}&root=1&page=1&num=100"
            resp = await client.get(list_url, headers=headers)
            data = resp.json()
            if data.get("errno", 0) != 0:
                raise RuntimeError(f"获取分享链接文件失败 (errno={data.get('errno')}): {data}")

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
        headers = self._get_headers()

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

        async with httpx.AsyncClient(timeout=30.0, headers=headers, follow_redirects=True) as client:
            resp = await client.post(transfer_url, params=params, data=data)
            res = resp.json()
            errno = res.get("errno", 0)
            if errno != 0:
                error_msg = {
                    -6: "Cookie (BDUSS) 或 Token 已过期，请重新获取粘贴。",
                    2: "参数错误。",
                    12: "网盘容量不足。",
                    4: "文件已存在于目标目录。",
                    -33: "分享转存次数超出限制。",
                }.get(errno, f"转存失败 (errno={errno})")
                raise RuntimeError(f"{error_msg} (详情: {res})")
            return res
