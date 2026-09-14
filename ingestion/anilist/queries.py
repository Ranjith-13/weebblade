# isAdult: false, because the other two sources already leave adult titles out
# of their season listings and AniList does not unless asked. The first live
# response, without it, was 13 hentai titles in 116; the whole catalogue from
# Kitsu and MAL held one.
#
# source(version: 3) for the full list of source types - see the note on
# _SOURCE_MATERIAL in transform.py.
SEASONAL_MEDIA_QUERY = """
query ($season: MediaSeason, $seasonYear: Int, $page: Int, $perPage: Int) {
  Page(page: $page, perPage: $perPage) {
    pageInfo {
      hasNextPage
    }
    media(season: $season, seasonYear: $seasonYear, type: ANIME, isAdult: false, sort: POPULARITY_DESC) {
      id
      idMal
      title {
        romaji
        english
        native
      }
      coverImage {
        large
        medium
      }
      description(asHtml: false)
      format
      status
      season
      seasonYear
      episodes
      duration
      genres
      source(version: 3)
      averageScore
      popularity
      favourites
      startDate {
        year
        month
        day
      }
      studios(isMain: true) {
        nodes {
          name
        }
      }
    }
  }
}
"""
