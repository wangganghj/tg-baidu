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

    # Ensure essential cookies are present
    if bduss and "BDUSS_BFESS" not in cookies_dict:
        cookies_dict["BDUSS_BFESS"] = bduss
    if "PANWEB" not in cookies_dict:
        cookies_dict["PANWEB"] = "1"

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
    Baidu Netdisk client utilizing BaiduPCSApi with multi-tier fallback for directory browsing and accurate VIP detection.
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
        """Initialize BaiduPCSApi instance without blocking network calls in __init__."""
        if not HAS_BAIDUPCS or not (self.bduss or self.cookies_dict):
            self._pcs_api = None
            return

        try:
            # Pass user_id=1 to prevent BaiduPCS from making synchronous tieba login requests in __init__
            self._pcs_api = BaiduPCSApi(
                bduss=self.bduss,
                stoken=self.stoken or None,
                cookies=self.cookies_dict or None,
                user_id=1,
            )
            # Update session headers with standard browser User-Agent
            if hasattr(self._pcs_api, "_baidupcs") and hasattr(self._pcs_api._baidupcs, "_session"):
                self._pcs_api._baidupcs._session.headers.update(
                    {
                        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                        "Referer": "https://pan.baidu.com/disk/home",
                    }
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
        """Verify cookie and retrieve accurate user information & VIP status."""
        if not self.is_configured():
            raise ValueError("尚未配置百度网盘 Cookie 或 BDUSS，请先在网页中绑定。")

        return await asyncio.to_thread(self._sync_get_user_info)

    def _sync_get_user_info(self) -> NetdiskUserInfo:
        if self._pcs_api is None:
            raise ValueError("BaiduPCS 引擎未初始化或不可用。")

        # 1. First verify connection and fetch quota using Baidu PCS API
        self._sync_get_quota()

        # 2. Fetch user profile and VIP status from pan APIs
        name = "百度网盘用户"
        uk = 0
        vip_type = 0
        avatar_url = ""

        session = self._pcs_api._baidupcs._session
        headers = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Referer": "https://pan.baidu.com/disk/home",
        }

        # Strategy A: xpan/nas?method=uinfo (Most accurate VIP & SVIP info)
        try:
            resp = session.get("https://pan.baidu.com/rest/2.0/xpan/nas?method=uinfo", headers=headers, timeout=5)
            if resp.status_code == 200:
                data = resp.json()
                if data.get("errno") == 0 or "netdisk_name" in data or "baidu_name" in data:
                    name = data.get("netdisk_name") or data.get("baidu_name") or name
                    uk = data.get("uk") or 0
                    avatar_url = data.get("avatar_url") or ""
                    is_svip = data.get("is_svip")
                    is_vip = data.get("is_vip")
                    raw_vip_type = data.get("vip_type")

                    if is_svip == 1 or raw_vip_type == 2:
                        vip_type = 2
                    elif is_vip == 1 or raw_vip_type == 1:
                        vip_type = 1
                    logger.info("Fetched user profile via xpan/nas: name=%s, vip_type=%s", name, vip_type)
        except Exception as e:
            logger.debug("xpan/nas uinfo lookup: %s", e)

        # Strategy B: pan.baidu.com/api/loginInfo fallback
        if not uk or vip_type == 0:
            try:
                resp = session.get("https://pan.baidu.com/api/loginInfo", headers=headers, timeout=5)
                if resp.status_code == 200:
                    data = resp.json()
                    linfo = data.get("login_info", {})
                    if linfo:
                        if name == "百度网盘用户":
                            name = linfo.get("baidu_name") or linfo.get("netdisk_name") or name
                        if not uk:
                            uk = linfo.get("uk") or 0
                        if not avatar_url:
                            avatar_url = linfo.get("avatar_url") or ""
                        # Check identity_type or is_svip
                        if linfo.get("identity_type") == 2 or linfo.get("vip_type") == 2 or linfo.get("is_svip") == 1:
                            vip_type = 2
                        elif (linfo.get("identity_type") == 1 or linfo.get("vip_type") == 1 or linfo.get("is_vip") == 1) and vip_type != 2:
                            vip_type = 1
            except Exception as e:
                logger.debug("pan loginInfo lookup: %s", e)

        # Strategy C: membership query
        if vip_type == 0:
            try:
                resp = session.get("https://pan.baidu.com/rest/2.0/membership/user?method=query&app_id=250528&web=1", headers=headers, timeout=5)
                if resp.status_code == 200:
                    mdata = resp.json()
                    for prod in mdata.get("product_infos", []):
                        cluster_type = str(prod.get("cluster_type", "")).lower()
                        product_name = str(prod.get("product_name", "")).lower()
                        if "svip" in cluster_type or "svip" in product_name or "超级会员" in product_name:
                            if prod.get("status") == 0 or prod.get("end_time", 0) > 0:
                                vip_type = 2
                                break
                        elif "vip" in cluster_type or "vip" in product_name or "会员" in product_name:
                            if prod.get("status") == 0 or prod.get("end_time", 0) > 0:
                                vip_type = 1
            except Exception as e:
                logger.debug("membership query lookup: %s", e)

        return NetdiskUserInfo(
            baidu_name=name,
            netdisk_name=name,
            uk=uk,
            vip_type=vip_type,
            avatar_url=avatar_url,
        )

    async def get_quota(self) -> NetdiskQuota:
        """Fetch storage quota information."""
        return await asyncio.to_thread(self._sync_get_quota)

    def _sync_get_quota(self) -> NetdiskQuota:
        if self._pcs_api is not None:
            try:
                pcs_quota = self._pcs_api.quota()
                total = getattr(pcs_quota, "quota", 0)
                if not total and isinstance(pcs_quota, (tuple, list)):
                    total = pcs_quota[0]
                used = getattr(pcs_quota, "used", 0)
                if not used and isinstance(pcs_quota, (tuple, list)):
                    used = pcs_quota[1]
                free = max(0, total - used)
                return NetdiskQuota(total=total, used=used, free=free)
            except Exception as e:
                err = str(e)
                logger.error("BaiduPCSApi get_quota failed: %s", e)
                if "-6" in err or "errno: -6" in err:
                    raise RuntimeError("Cookie / BDUSS 无效或已过期 (errno=-6)。请在 pan.baidu.com 重新登录并复制最新 Cookie。")
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
        """List files and folders in directory with multi-tier fallback."""
        return await asyncio.to_thread(self._sync_list_dir, dir_path)

    def _sync_list_dir(self, dir_path: str) -> List[NetdiskFile]:
        clean_dir = "/" + dir_path.strip("/") if dir_path != "/" else "/"
        if self._pcs_api is None:
            return []

        session = self._pcs_api._baidupcs._session
        headers = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Referer": "https://pan.baidu.com/disk/home",
        }

        # Strategy 1: Standard Web Pan API (pan.baidu.com/api/list)
        try:
            params = {
                "dir": clean_dir,
                "num": 1000,
                "order": "name",
                "desc": 0,
                "clienttype": 0,
                "app_id": 250528,
                "web": 1,
            }
            resp = session.get("https://pan.baidu.com/api/list", params=params, headers=headers, timeout=8)
            if resp.status_code == 200:
                data = resp.json()
                if data.get("errno") == 0 and "list" in data:
                    result = []
                    for item in data["list"]:
                        isdir = bool(item.get("isdir") in (1, "1", True) or item.get("dir") in (1, "1", True))
                        filename = item.get("server_filename") or posixpath.basename(item.get("path", ""))
                        result.append(
                            NetdiskFile(
                                fs_id=int(item.get("fs_id", 0)),
                                path=item.get("path", posixpath.join(clean_dir, filename)),
                                server_filename=filename,
                                size=int(item.get("size", 0)),
                                isdir=isdir,
                                category=int(item.get("category", 0)),
                                server_mtime=int(item.get("server_mtime", 0) or item.get("mtime", 0)),
                            )
                        )
                    logger.info("list_dir Strategy 1 (pan/api/list) for '%s' returned %d items.", clean_dir, len(result))
                    return result
        except Exception as e:
            logger.debug("list_dir Strategy 1 failed: %s", e)

        # Strategy 2: BaiduPCSApi.list (pcs.baidu.com/rest/2.0/pcs/file?method=list)
        try:
            pcs_files = self._pcs_api.list(clean_dir)
            result = []
            for f in pcs_files:
                filename = getattr(f, "server_filename", "") or (posixpath.basename(f.path) if f.path else "")
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
            logger.info("list_dir Strategy 2 (pcs.baidu.com) for '%s' returned %d items.", clean_dir, len(result))
            return result
        except Exception as e:
            logger.debug("list_dir Strategy 2 failed: %s", e)

        # Strategy 3: XPAN list API (pan.baidu.com/rest/2.0/xpan/file?method=list)
        try:
            params = {
                "method": "list",
                "dir": clean_dir,
                "num": 1000,
                "order": "name",
                "desc": 0,
            }
            resp = session.get("https://pan.baidu.com/rest/2.0/xpan/file", params=params, headers=headers, timeout=8)
            if resp.status_code == 200:
                data = resp.json()
                if data.get("errno") == 0 and "list" in data:
                    result = []
                    for item in data["list"]:
                        isdir = bool(item.get("isdir") in (1, "1", True))
                        filename = item.get("server_filename") or posixpath.basename(item.get("path", ""))
                        result.append(
                            NetdiskFile(
                                fs_id=int(item.get("fs_id", 0)),
                                path=item.get("path", posixpath.join(clean_dir, filename)),
                                server_filename=filename,
                                size=int(item.get("size", 0)),
                                isdir=isdir,
                                category=int(item.get("category", 0)),
                                server_mtime=int(item.get("server_mtime", 0) or item.get("mtime", 0)),
                            )
                        )
                    logger.info("list_dir Strategy 3 (xpan/file) for '%s' returned %d items.", clean_dir, len(result))
                    return result
        except Exception as e:
            logger.debug("list_dir Strategy 3 failed: %s", e)

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
            # 1. Try BaiduPCSApi makedir
            try:
                self._pcs_api.makedir(clean_dir)
                logger.info("Created directory on Baidu Netdisk: %s", clean_dir)
                return {"errno": 0, "path": clean_dir}
            except Exception as e:
                err = str(e)
                if "-8" in err or "already exists" in err:
                    return {"errno": 0, "path": clean_dir}

            # 2. Try Web Pan commit create
            try:
                session = self._pcs_api._baidupcs._session
                headers = {
                    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                    "Referer": "https://pan.baidu.com/disk/home",
                }
                params = {
                    "a": "commit",
                    "channel": "chunlei",
                    "web": 1,
                    "app_id": 250528,
                    "clienttype": 0,
                }
                data = {
                    "path": clean_dir,
                    "isdir": 1,
                    "size": 0,
                    "block_list": "[]",
                    "autoinit": 1,
                    "rtype": 1,
                }
                resp = session.post("https://pan.baidu.com/api/create", params=params, data=data, headers=headers, timeout=8)
                if resp.status_code == 200:
                    res_data = resp.json()
                    if res_data.get("errno") in (0, -8):
                        return {"errno": 0, "path": clean_dir}
            except Exception as e:
                logger.debug("create_dir Web fallback failed: %s", e)

        return {"errno": 0, "path": clean_dir}

    async def ensure_dir(self, dir_path: str) -> None:
        """Recursively ensure each parent directory exists on Baidu Netdisk."""
        clean_dir = "/" + dir_path.strip("/")
        parts = [p for p in clean_dir.split("/") if p]
        accumulated = ""
        for part in parts:
            accumulated += "/" + part
            await asyncio.to_thread(self._sync_create_dir, accumulated)

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
                self._sync_create_dir(clean_dest)
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
        self._sync_create_dir(clean_target)

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
            filename = getattr(p, "server_filename", "") or (posixpath.basename(p.path) if p.path else "file")
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

    async def get_share_content_info(self, share_url: str, share_pwd: str = "") -> Optional[Dict[str, Any]]:
        """Fetch title and shared items inside a Baidu Netdisk share link."""
        return await asyncio.to_thread(self._sync_get_share_content_info, share_url, share_pwd)

    def _sync_get_share_content_info(self, share_url: str, share_pwd: str = "") -> Optional[Dict[str, Any]]:
        import requests
        from .share_parser import BaiduShareParser
        share_link = BaiduShareParser.parse(share_url)
        if not share_link:
            return None
        surl = share_link.surl.lstrip("1")
        pwd = share_pwd or share_link.pwd

        session = self._pcs_api._baidupcs._session if (self._pcs_api and hasattr(self._pcs_api, "_baidupcs")) else requests.Session()
        session.headers.update({
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Referer": f"https://pan.baidu.com/s/1{surl}",
        })

        if pwd:
            try:
                verify_url = f"https://pan.baidu.com/share/verify?channel=chunlei&clienttype=0&web=1&app_id=250528&surl={surl}"
                session.post(verify_url, data={"pwd": pwd, "vcode": "", "vcode_str": ""}, timeout=8)
            except Exception as e:
                logger.debug("share verify exception: %s", e)

        try:
            list_url = f"https://pan.baidu.com/share/list?channel=chunlei&clienttype=0&web=1&app_id=250528&shorturl={surl}&root=1"
            resp = session.get(list_url, timeout=8)
            if resp.status_code == 200:
                data = resp.json()
                if data.get("errno") == 0:
                    return {
                        "title": data.get("title", ""),
                        "items": data.get("list", []),
                        "share_id": data.get("share_id"),
                        "uk": data.get("uk"),
                    }
        except Exception as e:
            logger.debug("share list exception: %s", e)

        return None
