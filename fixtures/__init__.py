"""Canonical fixture system for the AE 10-skill verification pilot."""

from .builder import FixtureBuildError, FixtureBuilder
from .manager import (
    FixtureCertificationError,
    FixtureRepository,
    sha256_file,
)
from .materializer import FixtureMaterializer
from .spec import (
    FixtureBuildPlan,
    FixtureSpecError,
    compile_all_fixture_plans,
    compile_fixture_plan,
)

__all__ = [
    "FixtureBuildError",
    "FixtureBuilder",
    "FixtureCertificationError",
    "FixtureRepository",
    "FixtureMaterializer",
    "FixtureBuildPlan",
    "FixtureSpecError",
    "compile_all_fixture_plans",
    "compile_fixture_plan",
    "sha256_file",
]
