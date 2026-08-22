"""
Baidu Netdisk Cookie-First Client.
Handles all operations (User Info, Quota, Directory Browser, File Renaming/Moving, and Share Transfer) via Cookie / BDUSS.
"""

from __future__ import annotations

import json
import logging
import posixpath
import re
import time
import urllib.parse
import uuid
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple
import httpx

logger = logging.getLogger(__name__)

PAN_BASE_URL = "https://pan.baidu.com"
XPAN_BASE_URL = "https://pan.baidu.com/rest/2.0/xpan"

PC_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
)
NETDISK_PC_UA = "netdisk;11.12.3;PC;PC-Windows;10.0.19042;WindowsBaiduYunGuanJia"


def parse_and_clean_cookie(raw_input: str) -> Tuple[str, str, str]:
    """
    Parse user cookie input.
    Accepts:
    1. Full Cookie string: "BAIDUID=...; BDUSS=...; STOKEN=...;"
    2. Key-value: "BDUSS=xxxx" or "BDUSS_BFESS=xxxx"
    3. Raw BDUSS value directly: "xxxx..."
    Returns: (full_cookie_str, bduss, stoken)
    """
    if not raw_input:
        return ("", "", "")

    raw = raw_input.strip().strip('"').strip("'")

    # 1. Extract BDUSS
    bduss = ""
    if "BDUSS=" in raw:
        m = re.search(r"(?:^|;\s*)BDUSS=([^;]+)", raw)
        if m:
            bduss = m.group(1).strip()
    elif "BDUSS_BFESS=" in raw:
        m = re.search(r"(?:^|;\s*)BDUSS_BFESS=([^;]+)", raw)
        if m:
            bduss = m.group(1).strip()
    elif "=" not in raw and len(raw) > 20:
        bduss = raw

    bduss = bduss.strip(";").strip('"').strip("'").strip()
    try:
        if "%" in bduss:
            bduss = urllib.parse.unquote(bduss)
    except Exception:
        pass

    # 2. Extract STOKEN
    stoken = ""
    m_stoken = re.search(r"(?:^|;\s*)STOKEN=([^;]+)", raw)
    if m_stoken:
        stoken = m_stoken.group(1).strip().strip(";").strip('"').strip("'")

    # 3. Assemble complete, reliable Cookie header string
    if "=" in raw:
        cookie_str = raw
        # Ensure BDUSS_BFESS is included if BDUSS is present
        if bduss and "BDUSS_BFESS" not in cookie_str:
            cookie_str += f"; BDUSS_BFESS={bduss}"
    else:
        cookie_str = f"BDUSS={bduss}; BDUSS_BFESS={bduss}"
        if stoken:
            cookie_str += f"; STOKEN={stoken}"

    return (cookie_str, bduss, stoken)


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
    """Baidu Netdisk client powered by Cookie / BDUSS authentication."""

    def __init__(
        self,
        cookie: str = "",
        bduss: str = "",
        stoken: str = "",
        auth_manager: Any = None,
        fallback_token: str = "",
    ):
        self.cookie, self.bduss, self.stoken = parse_and_clean_cookie(cookie or bduss)
        if bduss and not self.bduss:
            _, self.bduss, _ = parse_and_clean_cookie(bduss)
        self.auth_manager = auth_manager
        self.fallback_token = fallback_token

    def set_cookie(self, raw_input: str) -> None:
        """Update cookie dynamically."""
        self.cookie, self.bduss, self.stoken = parse_and_clean_cookie(raw_input)

    def is_configured(self) -> bool:
        """Check if any Cookie or BDUSS is configured."""
        return bool(self.cookie or self.bduss)

    def _get_headers(self, custom_ua: Optional[str] = None) -> Dict[str, str]:
        headers = {
            "User-Agent": custom_ua or PC_USER_AGENT,
            "Referer": "https://pan.baidu.com/disk/main",
            "Origin": "https://pan.baidu.com",
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            "X-Requested-With": "XMLHttpRequest",
        }
        cookie_header = self.cookie
        if not cookie_header and self.bduss:
            cookie_header = f"BDUSS={self.bduss}; BDUSS_BFESS={self.bduss}"
            if self.stoken:
                cookie_header += f"; STOKEN={self.stoken}"

        if cookie_header:
            if "PANWEB" not in cookie_header:
                cookie_header += "; PANWEB=1"
            if "BAIDUID" not in cookie_header:
                fake_baiduid = uuid.uuid4().hex.upper() + ":FG=1"
                cookie_header += f"; BAIDUID={fake_baiduid}"
            headers["Cookie"] = cookie_header
        return headers

    async def get_user_info(self) -> NetdiskUserInfo:
        """
        Verify Cookie and fetch user info.
        Tries multiple Baidu endpoints with robust fallback.
        """
        if not self.is_configured():
            raise ValueError("尚未配置百度网盘 Cookie 或 BDUSS，请先在网页中绑定。")

        headers = self._get_headers()

        async with httpx.AsyncClient(timeout=15.0, headers=headers, follow_redirects=True) as client:
            # 1. Try PC Client Netdisk UA with XPAN nas endpoint
            try:
                nas_headers = self._get_headers(custom_ua=NETDISK_PC_UA)
                resp = await client.get(f"{XPAN_BASE_URL}/nas?method=uinfo", headers=nas_headers)
                if resp.status_code == 200:
                    data = resp.json()
                    if data.get("errno", 0) == 0:
                        return NetdiskUserInfo(
                            baidu_name=data.get("baidu_name") or data.get("netdisk_name", "百度网盘用户"),
                            netdisk_name=data.get("netdisk_name", "百度网盘用户"),
                            uk=data.get("uk", 0),
                            vip_type=data.get("vip_type", 0),
                            avatar_url=data.get("avatar_url", ""),
                        )
            except Exception as e:
                logger.debug("xpan nas uinfo check failed: %s", e)

            # 2. Try template user info
            try:
                resp = await client.get("https://pan.baidu.com/api/gettemplateuser?web=1")
                if resp.status_code == 200:
                    data = resp.json()
                    records = data.get("records", [])
                    if records and isinstance(records, list):
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

            # 3. Try web userinfo
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

            # 4. Quota check (authoritative validator)
            try:
                resp = await client.get("https://pan.baidu.com/api/quota?checkexpire=1&checkfree=1")
                if resp.status_code == 200:
                    data = resp.json()
                    errno = data.get("errno", 0)
                    if errno == 0:
                        return NetdiskUserInfo(
                            baidu_name="百度网盘用户 (Cookie 连接)",
                            netdisk_name="已连接",
                            uk=0,
                            vip_type=0,
                            avatar_url="",
                        )
                    elif errno == -6:
                        raise RuntimeError("Cookie (BDUSS) 无效或已过期 (errno=-6)。请重新登录 pan.baidu.com 并复制最新 Cookie。")
                    else:
                        raise RuntimeError(f"Cookie 验证失败 (errno={errno})")
            except Exception as e:
                raise RuntimeError(f"{e}")

        raise ValueError("Cookie 验证失败，未能从百度网盘获取有效响应。")

    async def get_quota(self) -> NetdiskQuota:
        """Fetch storage quota information."""
        headers = self._get_headers()
        url = f"{PAN_BASE_URL}/api/quota?checkexpire=1&checkfree=1"

        async with httpx.AsyncClient(timeout=15.0, headers=headers, follow_redirects=True) as client:
            resp = await client.get(url)
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
        order: str = "name",
        desc: int = 0,
        start: int = 0,
        limit: int = 1000,
    ) -> List[NetdiskFile]:
        """List files and folders in directory with multi-strategy fallback."""
        headers = self._get_headers()
        clean_dir = "/" + dir_path.strip("/") if dir_path != "/" else "/"
        last_error = ""

        async with httpx.AsyncClient(timeout=15.0, headers=headers, follow_redirects=True) as client:
            # Strategy 1: Standard Web api/list with app_id 250528 and chunlei channel
            try:
                params: Dict[str, Any] = {
                    "dir": clean_dir,
                    "order": order,
                    "desc": desc,
                    "start": start,
                    "num": limit,
                    "page": 1,
                    "showempty": 0,
                    "web": "1",
                    "clienttype": 0,
                    "app_id": 250528,
                    "channel": "chunlei",
                    "dp-logid": str(int(time.time() * 1000)),
                }
                resp = await client.get(f"{PAN_BASE_URL}/api/list", params=params)
                if resp.status_code == 200:
                    data = resp.json()
                    errno = data.get("errno", 0)
                    if errno == 0:
                        return self._parse_file_list(data.get("list", []))
                    else:
                        last_error = f"api/list errno={errno}"
                        logger.info("list_dir Strategy 1 errno=%s: %s", errno, resp.text[:200])
            except Exception as e:
                logger.debug("api/list strategy 1 failed: %s", e)

            # Strategy 2: PC Client XPAN list endpoint with Netdisk UA
            try:
                pc_headers = self._get_headers(custom_ua=NETDISK_PC_UA)
                xpan_params: Dict[str, Any] = {
                    "method": "list",
                    "dir": clean_dir,
                    "order": order,
                    "desc": desc,
                    "start": start,
                    "limit": limit,
                    "clienttype": 0,
                    "app_id": 250528,
                }
                xpan_resp = await client.get(f"{XPAN_BASE_URL}/file", params=xpan_params, headers=pc_headers)
                if xpan_resp.status_code == 200:
                    xpan_data = xpan_resp.json()
                    errno = xpan_data.get("errno", 0)
                    if errno == 0:
                        return self._parse_file_list(xpan_data.get("list", []))
                    else:
                        last_error = f"xpan/file errno={errno}"
                        logger.info("list_dir Strategy 2 errno=%s: %s", errno, xpan_resp.text[:200])
            except Exception as e:
                logger.debug("xpan file/list strategy 2 failed: %s", e)

            # Strategy 3: Web api/list simple params without app_id
            try:
                params = {
                    "dir": clean_dir,
                    "order": order,
                    "desc": desc,
                    "start": start,
                    "num": limit,
                    "web": "1",
                }
                resp = await client.get(f"{PAN_BASE_URL}/api/list", params=params)
                if resp.status_code == 200:
                    data = resp.json()
                    errno = data.get("errno", 0)
                    if errno == 0:
                        return self._parse_file_list(data.get("list", []))
                    else:
                        last_error = f"api/list simple errno={errno}"
                        logger.info("list_dir Strategy 3 errno=%s: %s", errno, resp.text[:200])
            except Exception as e:
                logger.debug("api/list strategy 3 failed: %s", e)

            # Strategy 4: categorylist (if browsing root)
            if clean_dir == "/":
                try:
                    resp = await client.get(f"{PAN_BASE_URL}/api/categorylist?category=6&dir=%2F")
                    if resp.status_code == 200:
                        data = resp.json()
                        if data.get("errno", 0) == 0:
                            return self._parse_file_list(data.get("info", data.get("list", [])))
                except Exception as e:
                    logger.debug("categorylist strategy 4 failed: %s", e)

            if last_error:
                logger.warning("Baidu list_dir failed for '%s': %s", clean_dir, last_error)
            return []

    def _parse_file_list(self, raw_list: List[Dict[str, Any]]) -> List[NetdiskFile]:
        files = []
        for item in raw_list:
            is_dir_val = bool(item.get("isdir", 0) == 1 or item.get("isdir") is True or item.get("dir", 0) == 1)
            files.append(
                NetdiskFile(
                    fs_id=item.get("fs_id", 0),
                    path=item.get("path", ""),
                    server_filename=item.get("server_filename") or item.get("filename", ""),
                    size=item.get("size", 0),
                    isdir=is_dir_val,
                    category=item.get("category", 0),
                    server_mtime=item.get("server_mtime", 0),
                )
            )
        return files

    async def list_directories(self, dir_path: str = "/") -> List[Dict[str, Any]]:
        """List sub-directories in a specific path for the directory picker."""
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
        headers = self._get_headers()
        url = f"{PAN_BASE_URL}/api/create"
        data = {
            "path": dir_path,
            "size": 0,
            "isdir": 1,
            "block_list": json.dumps([]),
            "autoinit": 1,
            "rtype": 1,
        }

        async with httpx.AsyncClient(timeout=15.0, headers=headers, follow_redirects=True) as client:
            resp = await client.post(url, data=data)
            res = resp.json()
            # If errno is 0 or -8 (folder already exists), succeed
            if res.get("errno") not in (0, -8, None):
                # Fallback to xpan create
                xpan_url = f"{XPAN_BASE_URL}/file?method=create"
                xpan_resp = await client.post(xpan_url, data=data)
                res = xpan_resp.json()
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
        headers = self._get_headers()
        url = f"{PAN_BASE_URL}/api/filemanager"
        params = {"opera": opera}
        data = {
            "async": 0,
            "filelist": json.dumps(filelist, ensure_ascii=False),
        }

        async with httpx.AsyncClient(timeout=30.0, headers=headers, follow_redirects=True) as client:
            resp = await client.post(url, params=params, data=data)
            res = resp.json()
            if res.get("errno", 0) != 0:
                # Fallback to xpan filemanager
                xpan_url = f"{XPAN_BASE_URL}/file?method=filemanager&opera={opera}"
                xpan_resp = await client.post(xpan_url, data=data)
                res = xpan_resp.json()

            if res.get("errno", 0) != 0:
                logger.error("FileManager %s failed: %s", opera, res)
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
            # 1. Verify password if provided
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

            # 2. Get share file list
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

        transfer_url = f"{PAN_BASE_URL}/share/transfer"
        params = {
            "shareid": share_id,
            "from": from_uk,
            "ondup": "newcopy",
            "async": 1,
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
                    -6: "Cookie (BDUSS) 已失效或过期，请重新在网页端登录并更新 Cookie。",
                    2: "参数错误。",
                    12: "网盘容量不足。",
                    4: "文件已存在于目标目录。",
                    -33: "分享转存次数超出限制。",
                }.get(errno, f"转存失败 (errno={errno})")
                raise RuntimeError(f"{error_msg} (详情: {res})")
            return res
