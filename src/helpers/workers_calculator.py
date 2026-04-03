"""Hardware detection and optimal worker calculation"""
import os
import psutil
from typing import Tuple, Optional


class WorkerCalculator:
    """Calculate optimal worker count based on CPU cores"""
    
    MULTIPLIERS = {
        (1, 2): 2, (3, 4): 2.5, (5, 8): 3, (9, 16): 3.5, (17, 999): 4
    }
    MIN_WORKERS, MAX_WORKERS = 4, 100
    
    @staticmethod
    def get_physical_cores() -> int:
        """Get physical CPU cores (not threads)"""
        try:
            physical = psutil.cpu_count(logical=False)
            if physical and physical > 0:
                return physical
        except Exception:
            pass
        return max((os.cpu_count() or 4) // 2, 2)
    
    @staticmethod
    def get_logical_cores() -> int:
        """Get logical CPU cores (threads)"""
        return os.cpu_count() or 4
    
    @staticmethod
    def get_available_memory_gb() -> float:
        """Get available RAM in GB"""
        try:
            return psutil.virtual_memory().available / (1024 ** 3)
        except Exception:
            return 4.0
    
    @staticmethod
    def calculate_optimal_workers(
        physical_cores: Optional[int] = None,
        available_memory_gb: Optional[float] = None
    ) -> Tuple[int, str]:
        """Calculate optimal worker count
        
        Returns: (worker_count, info_string)
        """
        if physical_cores is None:
            physical_cores = WorkerCalculator.get_physical_cores()
        if available_memory_gb is None:
            available_memory_gb = WorkerCalculator.get_available_memory_gb()
        
        logical_cores = WorkerCalculator.get_logical_cores()
        
        # Find multiplier
        multiplier = 2
        for (low, high), mult in WorkerCalculator.MULTIPLIERS.items():
            if low <= physical_cores <= high:
                multiplier = mult
                break
        
        # Calculate workers
        workers = int(physical_cores * multiplier)
        
        # Memory constraint (~50MB per worker)
        max_by_memory = int(available_memory_gb * 1024 / 50)
        workers = min(workers, max_by_memory)
        
        # Apply bounds
        workers = max(WorkerCalculator.MIN_WORKERS, workers)
        workers = min(WorkerCalculator.MAX_WORKERS, workers)
        
        info = (
            f"CPU: {physical_cores} cores ({logical_cores} threads) | "
            f"RAM: {available_memory_gb:.1f}GB | Workers: {workers}"
        )
        
        return workers, info
    
    @staticmethod
    def get_system_info() -> dict:
        """Get system information"""
        physical = WorkerCalculator.get_physical_cores()
        logical = WorkerCalculator.get_logical_cores()
        workers, info = WorkerCalculator.calculate_optimal_workers()
        
        return {
            'physical_cores': physical,
            'logical_cores': logical,
            'available_memory_gb': WorkerCalculator.get_available_memory_gb(),
            'recommended_workers': workers,
            'info': info
        }