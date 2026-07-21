import os
import sys
import logging
import pkgutil
import importlib
from typing import Dict, Any, Type, Optional, List

logger = logging.getLogger(__name__)

class BaseRegistry:
    """
    Generic base class for auto-discovering and registering plugins in a directory.
    Provides caching to avoid scanning folders repeatedly.
    """
    def __init__(self, base_class: Type, module_prefix: str, scan_path: str):
        self.base_class = base_class
        self.module_prefix = module_prefix
        self.scan_path = scan_path
        self._registry: Dict[str, Type] = {}
        self._loaded = False

    def load_plugins(self) -> Dict[str, Type]:
        """Scans the directory, imports all modules, and registers valid subclasses."""
        if self._loaded:
            return self._registry

        if not os.path.exists(self.scan_path):
            # Fallback relative search
            proj_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
            parts = self.scan_path.replace("\\", "/").split("/")
            full_path = os.path.join(proj_root, *parts)
            if os.path.exists(full_path):
                self.scan_path = full_path
            else:
                logger.warning(f"Scan path does not exist: {self.scan_path}")
                self._loaded = True
                return self._registry

        logger.info(f"Scanning for plugins in {self.scan_path}...")
        
        # Ensure path is importable
        dir_to_add = os.path.dirname(self.scan_path)
        if dir_to_add not in sys.path:
            sys.path.insert(0, dir_to_add)

        for _, module_name, is_pkg in pkgutil.iter_modules([self.scan_path]):
            if is_pkg:
                continue
            full_module_name = f"{self.module_prefix}.{module_name}"
            try:
                module = importlib.import_module(full_module_name)
                for attr_name in dir(module):
                    attr = getattr(module, attr_name)
                    if (
                        isinstance(attr, type) 
                        and issubclass(attr, self.base_class) 
                        and attr is not self.base_class
                    ):
                        name = getattr(attr, "name", attr.__name__.lower())
                        self._registry[name] = attr
                        logger.debug(f"Registered plugin '{name}': {attr}")
            except Exception as e:
                logger.error(f"Failed to load module {full_module_name}: {e}", exc_info=True)

        self._loaded = True
        return self._registry

    def get(self, name: str) -> Optional[Type]:
        self.load_plugins()
        return self._registry.get(name)

    def get_all(self) -> Dict[str, Type]:
        self.load_plugins()
        return self._registry

    def get_registered_names(self) -> List[str]:
        self.load_plugins()
        return list(self._registry.keys())
