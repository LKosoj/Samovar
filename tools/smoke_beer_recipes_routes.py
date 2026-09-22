#!/usr/bin/env python3
"""Каталог рецептов пива и импорт BeerXML на brewxml.htm без промежуточного хранилища."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
program = (ROOT / "data_raw/program.htm").read_text(encoding="utf-8")
brewxml = (ROOT / "data_raw/brewxml.htm").read_text(encoding="utf-8")
beer = (ROOT / "data_raw/beer.htm").read_text(encoding="utf-8")
assets = (ROOT / "tools/build_web_assets.py").read_text(encoding="utf-8")
errors = []

for token in (
    "https://www.samovar-tool.ru/beerxml/v1/",
    "/cheese-recipes-bootstrap",
    'id="beerRecipesCard"',
    "hidden",
    "function selectCatalogRecipe(",
    'applyRecipeText(xml, "BeerXML", generation)',
    "showRecipeSource(item.name || item.slug)",
    "SamovarApp.applyModeNavigation(bootstrap.mode)",
):
    if token not in brewxml:
        errors.append("brewxml.htm missing " + token)

for forbidden in ("beerRecipesCard", "beerxml/v1", "cheese-recipes-bootstrap"):
    if forbidden in program:
        errors.append("program.htm must contain only the rectification calculator: " + forbidden)

for forbidden in ("sessionStorage", "BEER_RECIPE_STORAGE_KEY", "loadPendingBeerRecipe", "location.href = 'brewxml.htm'"):
    if forbidden in brewxml:
        errors.append("brewxml.htm must apply the selected recipe directly: " + forbidden)

for token in ("function applyRecipeText(", "function get_brew_info(", 'id="recipeSource"'):
    if token not in brewxml:
        errors.append("brewxml.htm missing recipe import " + token)

for token in ("id='beerRecipesTab'", 'value="Рецепты"', "SamovarApp.confirmLeave()", 'location.href="brewxml.htm"'):
    if token not in beer:
        errors.append("beer.htm missing recipes entry " + token)

for name in ('"program.htm"', '"brewxml.htm"'):
    if name not in assets:
        errors.append(f"build_web_assets.py does not generate {name}.gz")

if errors:
    raise SystemExit("\n".join(errors))
print("beer recipes route contract passed")
