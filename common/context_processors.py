from common.parsing import is_hex_colour


def school_context(request):
    school = getattr(request, "school", None)
    return {
        "current_school": school,
        "brand_colour": school.brand_colour if school and is_hex_colour(school.brand_colour) else "#143A2B",
        "school_slug": school.slug if school else "",
        "impersonating": bool(getattr(request, "session", {}).get("impersonator_id")),
    }
