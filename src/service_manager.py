"""
memcore-cloud Service Manager Abstraction
统一整改 Module C: 隔离systemctl/systemd到平台特定实现

core层不再直接调用systemctl，所有服务管理通过ServiceManager接口。
"""
import sys
import subprocess
from typing import Optional, List, Dict

class ServiceManagerInterface:
    """服务管理抽象接口"""
    def list_units(self, unit_type: str = "service") -> List[Dict]:
        raise NotImplementedError

    def is_active(self, unit_name: str) -> bool:
        raise NotImplementedError

    def status(self, unit_name: str) -> Dict:
        raise NotImplementedError


class LinuxServiceManager(ServiceManagerInterface):
    """Linux实现：使用systemctl"""
    def list_units(self, unit_type: str = "service") -> List[Dict]:
        try:
            result = subprocess.run(
                ["systemctl", "list-units", f"--type={unit_type}", "--no-pager", "--plain"],
                capture_output=True, text=True, timeout=10
            )
            units = []
            for line in result.stdout.strip().split("\n")[1:]:
                parts = line.split()
                if len(parts) >= 4:
                    units.append({
                        "name": parts[0],
                        "load": parts[1],
                        "active": parts[2],
                        "sub": parts[3],
                    })
            return units
        except Exception:
            return []

    def is_active(self, unit_name: str) -> bool:
        try:
            result = subprocess.run(
                ["systemctl", "is-active", unit_name],
                capture_output=True, text=True, timeout=2
            )
            return result.stdout.strip() == "active"
        except Exception:
            return False

    def status(self, unit_name: str) -> Dict:
        try:
            result = subprocess.run(
                ["systemctl", "status", unit_name, "--no-pager"],
                capture_output=True, text=True, timeout=5
            )
            return {
                "output": result.stdout,
                "returncode": result.returncode
            }
        except Exception as e:
            return {"error": str(e)}


class StubServiceManager(ServiceManagerInterface):
    """非Linux平台stub：返回空结果"""
    def list_units(self, unit_type: str = "service") -> List[Dict]:
        return []

    def is_active(self, unit_name: str) -> bool:
        return False

    def status(self, unit_name: str) -> Dict:
        return {"error": "stub: not implemented on this platform"}


def get_service_manager() -> ServiceManagerInterface:
    """
    根据当前平台返回对应的ServiceManager。
    Linux返回真实实现，其他平台返回stub。
    """
    if sys.platform == "linux":
        return LinuxServiceManager()
    return StubServiceManager()
