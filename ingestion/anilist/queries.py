SEASONAL_MEDIA_QUERY = """
query ($season: MediaSeason, $seasonYear: Int, $page: Int, $perPage: Int) {
  Page(page: $page, perPage: $perPage) {
    pageInfo {
      hasNextPage
    }
    media(season: $season, seasonYear: $seasonYear, type: ANIME, sort: POPULARITY_DESC) {
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
      source
      averageScore
      meanScore
      popularity
      favourites
      trending
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
