"""Schema extraction module for Schema Audit Lead Generator.

Fetches website HTML and extracts LocalBusiness structured data (JSON-LD).
"""

import warnings
from urllib.parse import urlparse

import extruct
import requests
from w3lib.html import get_base_url

from config import REQUEST_TIMEOUT

# Schema.org LocalBusiness type and all common subtypes
LOCAL_BUSINESS_TYPES: set[str] = {
    "LocalBusiness",
    "Organization",
    "ProfessionalService",
    "PlumbingService",
    "Plumber",
    "ElectricalService",
    "Electrician",
    "HVACBusiness",
    "HomeAndConstructionBusiness",
    "GeneralContractor",
    "RoofingContractor",
    "MovingCompany",
    "HousePainter",
    "Locksmith",
    "LegalService",
    "Attorney",
    "Notary",
    "FinancialService",
    "AccountingService",
    "InsuranceAgency",
    "HealthAndBeautyBusiness",
    "BeautySalon",
    "HairSalon",
    "DaySpa",
    "NailSalon",
    "TattooParlor",
    "AutoRepair",
    "AutoBodyShop",
    "AutoDealer",
    "AutoPartsStore",
    "AutoRental",
    "AutoWash",
    "GasStation",
    "MotorcycleDealer",
    "MotorcycleRepair",
    "Dentist",
    "MedicalBusiness",
    "MedicalClinic",
    "Pharmacy",
    "Physician",
    "Optician",
    "Veterinarian",
    "RealEstateAgent",
    "Restaurant",
    "BarOrPub",
    "CafeOrCoffeeShop",
    "FastFoodRestaurant",
    "IceCreamShop",
    "Bakery",
    "Store",
    "ClothingStore",
    "ConvenienceStore",
    "ElectronicsStore",
    "Florist",
    "FurnitureStore",
    "GardenStore",
    "GroceryStore",
    "HardwareStore",
    "HobbyShop",
    "HomeGoodsStore",
    "JewelryStore",
    "LiquorStore",
    "MensClothingStore",
    "MobilePhoneStore",
    "MovieRentalStore",
    "MusicStore",
    "OfficeEquipmentStore",
    "OutletStore",
    "PawnShop",
    "PetStore",
    "ShoeStore",
    "SportingGoodsStore",
    "TireShop",
    "ToyStore",
    "WholesaleStore",
    "WomensClothingStore",
    "AnimalShelter",
    "ChildCare",
    "DryCleaningOrLaundry",
    "EmergencyService",
    "EmploymentAgency",
    "EntertainmentBusiness",
    "ExerciseGym",
    "FinancialService",
    "FoodEstablishment",
    "GovernmentOffice",
    "HealthClub",
    "InternetCafe",
    "Library",
    "LodgingBusiness",
    "Hotel",
    "Motel",
    "BedAndBreakfast",
    "Hostel",
    "MedicalOrganization",
    "ProfessionalService",
    "RadioStation",
    "RecyclingCenter",
    "SelfStorage",
    "ShoppingCenter",
    "SportsActivityLocation",
    "TelevisionStation",
    "TouristInformationCenter",
    "TravelAgency",
}


class SchemaExtractor:
    """Extract LocalBusiness schema from websites."""

    def __init__(self, timeout: int = REQUEST_TIMEOUT) -> None:
        self.timeout = timeout
        self.headers = {
            "User-Agent": "Mozilla/5.0 (compatible; SchemaAuditBot/1.0)"
        }

    def normalize_url(self, url: str) -> str:
        """Add https:// if scheme is missing."""
        url = url.strip()
        parsed = urlparse(url)
        if not parsed.scheme:
            return f"https://{url}"
        return url

    def fetch_html(self, url: str) -> str | None:
        """Fetch HTML content from URL. Returns None if request fails."""
        url = self.normalize_url(url)
        try:
            resp = requests.get(
                url,
                headers=self.headers,
                timeout=self.timeout,
                allow_redirects=True,
            )
            resp.raise_for_status()
            return resp.text
        except requests.RequestException as exc:
            print(f"  WARNING: Could not fetch {url}: {exc}")
            return None

    def extract_all_metadata(self, html: str, base_url: str) -> dict:
        """Use extruct to extract JSON-LD structured data.

        Args:
            html: Raw HTML content.
            base_url: The URL the HTML was fetched from (for resolving relative URLs).

        Returns:
            Dict with 'json-ld' key containing list of JSON-LD blocks.
        """
        resolved_base = get_base_url(html, base_url)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            metadata = extruct.extract(
                html,
                base_url=resolved_base,
                syntaxes=["json-ld"],
                uniform=True,
            )
        return metadata

    def _is_local_business_type(self, schema_type: str | list | None) -> bool:
        """Check whether a @type value matches a LocalBusiness type."""
        if schema_type is None:
            return False
        if isinstance(schema_type, str):
            return schema_type in LOCAL_BUSINESS_TYPES
        if isinstance(schema_type, list):
            return any(t in LOCAL_BUSINESS_TYPES for t in schema_type)
        return False

    def find_local_business_schema(self, metadata: dict) -> list[dict]:
        """Filter JSON-LD blocks for LocalBusiness and subtypes.

        Handles:
          - @type as a string or a list of strings
          - @graph arrays (common in Yoast/RankMath SEO plugins)

        Returns:
            List of matching schema blocks (may be empty).
        """
        jsonld_blocks: list[dict] = metadata.get("json-ld", [])
        matching: list[dict] = []

        for block in jsonld_blocks:
            # Check if this block itself has a matching @type
            if self._is_local_business_type(block.get("@type")):
                matching.append(block)
                continue

            # Check @graph array (Yoast, RankMath, etc.)
            graph = block.get("@graph")
            if isinstance(graph, list):
                for node in graph:
                    if isinstance(node, dict) and self._is_local_business_type(node.get("@type")):
                        matching.append(node)

        return matching

    def extract_schema_from_url(self, url: str) -> list[dict] | None:
        """Full workflow: fetch HTML -> extract metadata -> filter for LocalBusiness.

        Returns:
            list of schema blocks if site was reachable (may be empty),
            None if the fetch failed entirely.
        """
        normalized = self.normalize_url(url)
        html = self.fetch_html(normalized)
        if html is None:
            return None

        metadata = self.extract_all_metadata(html, normalized)
        return self.find_local_business_schema(metadata)
