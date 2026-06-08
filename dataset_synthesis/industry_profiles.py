"""
Industry profiles for the 100-company stress-test dataset.

Defines 10 industry categories x 10 companies = 100 companies. Each industry
declares an industry-specialized tab with industry-specific columns and value
ranges (e.g. biogas methane output, t-shirt screen count, tractor engine specs).

Column spec format (per specialty column):
    (kind, params)
  kinds:
    "float"  -> params: (low, high)
    "int"    -> params: (low, high)
    "choice" -> params: [options...]
    "id"     -> params: "PREFIX"   (PREFIX-#####)
"""

from typing import Dict, List, Any

# Each industry: list of 10 (company_slug, display_name), specialty tab name,
# and specialty column specs. Domain tag links the specialty tab to one of the
# 47 OmniusGrid DomainTypes for compatibility outputs.

INDUSTRIES: Dict[str, Dict[str, Any]] = {
    "textile_apparel": {
        "domain": "PRODUCTION_OEE",
        "specialty_tab": "Apparel_Production",
        "companies": [
            "tshirt_screen_printing", "denim_jeans", "technical_sportswear",
            "home_textiles", "carpet_rug", "industrial_fabric",
            "embroidery_applique", "leather_goods", "knitwear", "uniform_workwear",
        ],
        "specialty_columns": {
            "screen_count": ("int", (1, 12)),
            "ink_type": ("choice", ["Plastisol", "Water-based", "Discharge", "Silicone"]),
            "mesh_count": ("int", (60, 305)),
            "flash_cure_time_s": ("float", (2.0, 12.0)),
            "garment_type": ("choice", ["Tee", "Hoodie", "Polo", "Tank", "Longsleeve"]),
            "fabric_gsm": ("int", (120, 380)),
            "print_defect_type": ("choice", ["None", "Registration", "Smudge", "Underbase", "Crack"]),
            "wash_test_rating": ("int", (1, 5)),
        },
    },
    "heavy_equipment": {
        "domain": "MANUFACTURING_EXECUTION_SYSTEM",
        "specialty_tab": "Equipment_Assembly",
        "companies": [
            "biogas_processing", "farm_tractor", "air_compressor_tank",
            "construction_equipment", "mining_equipment", "industrial_crane",
            "excavator_bulldozer", "agricultural_machinery", "forklift_handling",
            "industrial_pump",
        ],
        "specialty_columns": {
            "engine_horsepower": ("int", (20, 600)),
            "hydraulic_pressure_psi": ("int", (1500, 5000)),
            "methane_output_m3_day": ("float", (0.0, 5000.0)),
            "tank_capacity_liters": ("int", (50, 20000)),
            "weld_seam_count": ("int", (4, 120)),
            "load_test_result": ("choice", ["Pass", "Pass", "Pass", "Marginal", "Fail"]),
            "assembly_time_hours": ("float", (2.0, 80.0)),
            "field_test_hours": ("float", (0.0, 200.0)),
        },
    },
    "chemical_process": {
        "domain": "QUALITY_CONTROL",
        "specialty_tab": "Process_Chemistry",
        "companies": [
            "pharmaceutical", "paint_coating", "adhesive_sealant", "plastic_resin",
            "fertilizer", "pesticide", "industrial_chemical", "petrochemical",
            "specialty_chemical", "water_treatment_equip",
        ],
        "specialty_columns": {
            "reactor_temp_c": ("float", (20.0, 320.0)),
            "reaction_pressure_bar": ("float", (1.0, 50.0)),
            "ph_level": ("float", (1.0, 14.0)),
            "batch_purity_percent": ("float", (90.0, 99.99)),
            "viscosity_cp": ("float", (1.0, 100000.0)),
            "catalyst_type": ("choice", ["Pt", "Pd", "Ni", "Zeolite", "Enzyme", "None"]),
            "curing_time_min": ("int", (5, 480)),
            "hazmat_class": ("choice", ["None", "Flammable", "Corrosive", "Toxic", "Oxidizer"]),
        },
    },
    "food_beverage": {
        "domain": "QUALITY_CONTROL",
        "specialty_tab": "Food_Processing",
        "companies": [
            "beverage_bottling", "snack_food", "dairy", "meat_processing",
            "bakery", "confectionery", "frozen_food", "canned_food",
            "spice_seasoning", "brewery",
        ],
        "specialty_columns": {
            "cook_temp_c": ("float", (4.0, 200.0)),
            "cold_chain_temp_c": ("float", (-30.0, 8.0)),
            "fill_volume_ml": ("int", (100, 2000)),
            "brix_level": ("float", (0.0, 30.0)),
            "shelf_life_days": ("int", (3, 730)),
            "haccp_ccp_status": ("choice", ["In-Spec", "In-Spec", "Deviation", "Critical"]),
            "allergen_flag": ("choice", ["None", "Gluten", "Dairy", "Nuts", "Soy"]),
            "microbial_count_cfu": ("int", (0, 100000)),
        },
    },
    "electronics_tech": {
        "domain": "EDGE_AI_TELEMETRY",
        "specialty_tab": "Electronics_Fab",
        "companies": [
            "semiconductor", "pcb", "consumer_electronics", "industrial_electronics",
            "battery", "led_lighting", "solar_panel", "cable_wire",
            "sensor", "power_supply",
        ],
        "specialty_columns": {
            "wafer_yield_percent": ("float", (60.0, 99.9)),
            "solder_defect_ppm": ("int", (0, 5000)),
            "cleanroom_class": ("choice", ["ISO5", "ISO6", "ISO7", "ISO8"]),
            "test_voltage_v": ("float", (1.0, 480.0)),
            "thermal_cycles": ("int", (0, 1000)),
            "esd_event_count": ("int", (0, 50)),
            "component_count": ("int", (10, 5000)),
            "burn_in_hours": ("float", (0.0, 168.0)),
        },
    },
    "metal_fabrication": {
        "domain": "PRODUCTION_OEE",
        "specialty_tab": "Metal_Fab",
        "companies": [
            "steel", "aluminum_extrusion", "sheet_metal", "casting_forging",
            "metal_stamping", "welding_fabrication", "precision_machining",
            "fastener", "pipe_tube", "structural_steel",
        ],
        "specialty_columns": {
            "furnace_temp_c": ("int", (600, 1700)),
            "tensile_strength_mpa": ("int", (200, 2000)),
            "tolerance_mm": ("float", (0.001, 2.0)),
            "weld_penetration_mm": ("float", (0.5, 25.0)),
            "surface_finish_ra": ("float", (0.1, 25.0)),
            "press_tonnage": ("int", (10, 4000)),
            "scrap_metal_kg": ("float", (0.0, 5000.0)),
            "coating_thickness_um": ("float", (1.0, 500.0)),
        },
    },
    "automotive_transport": {
        "domain": "MANUFACTURING_EXECUTION_SYSTEM",
        "specialty_tab": "Vehicle_Assembly",
        "companies": [
            "automobile", "truck", "motorcycle", "rv_trailer", "marine_vessel",
            "railway_equipment", "aircraft_component", "tire",
            "automotive_parts", "engine",
        ],
        "specialty_columns": {
            "line_takt_time_s": ("float", (30.0, 600.0)),
            "torque_spec_nm": ("float", (5.0, 800.0)),
            "paint_booth_humidity": ("float", (30.0, 80.0)),
            "vin_sequence": ("int", (1, 999999)),
            "road_test_km": ("float", (0.0, 200.0)),
            "weld_robot_id": ("id", "ROBOT"),
            "torque_audit_result": ("choice", ["Pass", "Pass", "Pass", "Rework"]),
            "emissions_test_g_km": ("float", (0.0, 250.0)),
        },
    },
    "packaging_paper": {
        "domain": "PACKAGING",
        "specialty_tab": "Packaging_Line",
        "companies": [
            "corrugated_box", "plastic_packaging", "glass_bottle", "paper",
            "label_sticker", "flexible_packaging", "pallet", "container",
            "closure_cap", "carton",
        ],
        "specialty_columns": {
            "line_speed_units_min": ("int", (50, 1200)),
            "board_grade": ("choice", ["B-flute", "C-flute", "E-flute", "Double-wall"]),
            "burst_strength_kpa": ("int", (100, 1400)),
            "print_registration_mm": ("float", (0.0, 3.0)),
            "seal_integrity": ("choice", ["Pass", "Pass", "Pass", "Leak"]),
            "roll_diameter_mm": ("int", (200, 1500)),
            "waste_trim_percent": ("float", (0.0, 15.0)),
            "gsm": ("int", (60, 600)),
        },
    },
    "building_materials": {
        "domain": "PRODUCTION_OUTPUT",
        "specialty_tab": "Materials_Production",
        "companies": [
            "cement", "brick", "ceramic_tile", "window_door", "insulation",
            "roofing", "drywall", "flooring", "prefab_building", "concrete_block",
        ],
        "specialty_columns": {
            "kiln_temp_c": ("int", (800, 1500)),
            "cure_time_hours": ("float", (1.0, 72.0)),
            "compressive_strength_mpa": ("float", (5.0, 80.0)),
            "moisture_content_percent": ("float", (0.0, 25.0)),
            "batch_volume_m3": ("float", (0.5, 50.0)),
            "density_kg_m3": ("int", (300, 2600)),
            "dimensional_tolerance_mm": ("float", (0.1, 10.0)),
            "thermal_r_value": ("float", (0.5, 60.0)),
        },
    },
    "medical_healthcare": {
        "domain": "QUALITY_CONTROL",
        "specialty_tab": "Medical_Device_QA",
        "companies": [
            "medical_device", "surgical_instrument", "diagnostic_equipment",
            "orthopedic_implant", "dental_equipment", "hospital_equipment",
            "lab_equipment", "pharma_packaging", "disposable_supply",
            "rehabilitation_equipment",
        ],
        "specialty_columns": {
            "sterility_assurance_level": ("choice", ["10^-6", "10^-5", "10^-4"]),
            "bioburden_cfu": ("int", (0, 1000)),
            "lot_release_status": ("choice", ["Released", "Released", "Quarantine", "Rejected"]),
            "udi_code": ("id", "UDI"),
            "biocompatibility_pass": ("choice", ["Yes", "Yes", "Yes", "No"]),
            "cleanroom_particle_count": ("int", (0, 100000)),
            "validation_status": ("choice", ["IQ", "OQ", "PQ", "Validated"]),
            "dimensional_cpk": ("float", (0.8, 2.5)),
        },
    },
}


def all_companies() -> List[Dict[str, Any]]:
    """Return a flat ordered list of the 100 companies with metadata."""
    companies: List[Dict[str, Any]] = []
    idx = 0
    for industry, profile in INDUSTRIES.items():
        for slug in profile["companies"]:
            idx += 1
            companies.append({
                "index": idx,
                "company_id": f"COMP-{idx:03d}",
                "slug": slug,
                "industry": industry,
                "domain": profile["domain"],
                "specialty_tab": profile["specialty_tab"],
                "specialty_columns": profile["specialty_columns"],
                "file_stub": f"company_{idx:02d}_{slug}",
            })
    return companies


if __name__ == "__main__":
    comps = all_companies()
    print(f"Total companies: {len(comps)}")
    for c in comps[:3] + comps[-1:]:
        print(c["company_id"], c["industry"], c["slug"], "->", c["specialty_tab"])
