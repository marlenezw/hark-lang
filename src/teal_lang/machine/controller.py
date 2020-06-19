"""Placeholder for the controller class"""

from dataclasses import dataclass
from typing import List, Dict, Tuple
from .types import TlType


@dataclass(frozen=True)
class ErrorInfo:
    traceback: list


# TODO implement interface
class Controller:
    pass


@dataclass(frozen=True)
class ARecPtr:
    """Pointer to an activation record"""

    thread: int
    arec_idx: int


@dataclass
class ActivationRecord:
    """Like a stack frame, but more general.

    NOTE static_chain: ARecPtr: Not needed - we don't have nested lexical scopes

    """

    dynamic_chain: ARecPtr  # ........ Pointer to caller activation record
    return_ip: int  # ................ IP to return to
    # parameters: List[TlType]  # ...... Function parameters
    bindings: Dict[str, TlType]  # ... Local bindings
    # result: TlType  # ................ Function return value
    ref_count: int  # ................ Number of places this AR is used
