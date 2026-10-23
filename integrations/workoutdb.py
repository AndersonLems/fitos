"""WorkoutDB.

Avaliação (out/2026): os domínios públicos conhecidos (workoutdb.io / api.workoutdb.io) não
responderam e não há documentação de API acessível. A integração NÃO está implementada e o
FitOS não simula dados desta fonte. Se uma API documentada surgir, implementar aqui seguindo
o mesmo contrato de `exercisedb.normalize`.
"""
from __future__ import annotations

from .base import IntegrationUnavailable

AVAILABLE = False


def iter_exercises():
    raise IntegrationUnavailable("WorkoutDB sem API pública acessível; integração não implementada")
