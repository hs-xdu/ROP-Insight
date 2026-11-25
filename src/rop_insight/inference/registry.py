"""One explicit adapter registry for GUI, checks and reproducibility scripts."""

from rop_insight.inference.vascx import VascXAdapter
from rop_insight.inference.a6 import A6Adapter
from rop_insight.inference.imported_ridge import ImportedRidgeAdapter
from rop_insight.inference.quantification import QuantificationAdapter
from rop_insight.inference.svm import FrozenSVMAdapter


def production_registry():
    return dict(vascx_native=VascXAdapter,a6_shenzhen=A6Adapter,imported_ridge=ImportedRidgeAdapter,
                chapter5_quant=QuantificationAdapter,chapter5_svm=FrozenSVMAdapter)
