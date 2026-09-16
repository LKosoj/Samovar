#!/usr/bin/env python3
"""T3: карточка «Рецепты пива с сайта» в program.htm и приём рецепта в brewxml.htm —
маркеры в исходниках и запрет второго конвертера (см. docs/plans/2026-09-16-beer-tasks/T3-firmware.md)."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
program = (ROOT / "data_raw/program.htm").read_text(encoding="utf-8")
brewxml = (ROOT / "data_raw/brewxml.htm").read_text(encoding="utf-8")
assets = (ROOT / "tools/build_web_assets.py").read_text(encoding="utf-8")
errors = []

for token in (
    "https://www.samovar-tool.ru/beerxml/v1/",
    "/cheese-recipes-bootstrap",
    'id="beerRecipesCard"',
    "hidden",
    "sessionStorage.setItem(STORAGE_KEY",
    "STORAGE_KEY = 'samovar.beerxml.pending'",
    "'brewxml.htm'",
):
    if token not in program:
        errors.append("program.htm missing " + token)

for forbidden in ("function get_brew_info", "function convertRecipe", "MASH_STEPS"):
    if forbidden in program:
        errors.append("program.htm must not duplicate the recipe converter: " + forbidden)

for token in (
    'sessionStorage.getItem(BEER_RECIPE_STORAGE_KEY)',
    'sessionStorage.removeItem(BEER_RECIPE_STORAGE_KEY)',
    "function applyRecipeText(",
    "function get_brew_info(",
    "function loadPendingBeerRecipe(",
    'id="recipeSource"',
):
    if token not in brewxml:
        errors.append("brewxml.htm missing " + token)

for name in ('"program.htm"', '"brewxml.htm"'):
    if name not in assets:
        errors.append(f"build_web_assets.py does not generate {name}.gz")

if errors:
    raise SystemExit("\n".join(errors))
print("beer recipes route contract passed")
