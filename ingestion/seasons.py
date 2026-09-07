def season_for_month(month: int) -> str:
    """Map a calendar month to the anime industry's quarterly season (WINTER = Jan-Mar).

    Shared across sources — AniList, Jikan/MAL, and Kitsu all use this same quarterly
    convention, just with different casing in their own APIs.
    """
    if month in (1, 2, 3):
        return "WINTER"
    if month in (4, 5, 6):
        return "SPRING"
    if month in (7, 8, 9):
        return "SUMMER"
    return "FALL"
