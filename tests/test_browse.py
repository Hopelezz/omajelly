from __future__ import annotations

import unittest
from unittest import mock

from omajelly import browse as browse_module
from omajelly.browse import BrowseKind, SearchScope, browse_document
from tests.support import (
    EP1,
    EP2,
    EP3,
    EP4,
    MOVIE,
    MOVIE_LIB,
    NOW,
    SEASON1,
    SEASON2,
    SHOW,
    SHOW_LIB,
    USER,
    FakeClient,
    episode,
    items,
    movie,
    season,
    series,
)


CONFIG = {
    "userId": USER,
    "movieSectionIds": [MOVIE_LIB],
    "tvSectionIds": [SHOW_LIB],
}


class JellyfinBrowseTests(unittest.TestCase):
    def test_browse_normalizes_shows_and_pages(self):
        client = FakeClient(
            {
                "IncludeItemTypes=Series": {
                    "Items": [
                        series(SHOW, "Series", leaf_count=10, unplayed=7, created=NOW)
                    ],
                    "TotalRecordCount": 1,
                }
            }
        )
        document = browse_document(
            client, CONFIG, BrowseKind.SHOWS, "", 0, 40
        )
        self.assertEqual(document["total"], 1)
        self.assertEqual(document["items"][0]["watchState"], "started")
        self.assertFalse(document["items"][0]["playable"])

    def test_fuzzy_search_respects_scope_and_expands_season_codes(self):
        client = FakeClient(
            {
                "IncludeItemTypes=Movie": items(
                    movie(MOVIE, "Alone Together", created=NOW)
                ),
                "IncludeItemTypes=Series": items(
                    series(SHOW, "Alone", leaf_count=3, unplayed=3, created=NOW)
                ),
                "IncludeItemTypes=Episode": items(
                    episode(
                        EP2,
                        "Alone",
                        series_id=SHOW,
                        season=1,
                        index=2,
                        title="Second",
                        created=NOW,
                    ),
                    episode(
                        EP1,
                        "Alone",
                        series_id=SHOW,
                        season=1,
                        index=1,
                        title="First",
                        created=NOW,
                    ),
                    episode(
                        EP3,
                        "Alone",
                        series_id=SHOW,
                        season=2,
                        index=1,
                        title="Later",
                        created=NOW,
                    ),
                ),
            }
        )
        with (
            mock.patch.object(browse_module, "utc_now", return_value=NOW),
            mock.patch.object(browse_module.shutil, "which", return_value=None),
        ):
            movies = browse_document(
                client,
                CONFIG,
                BrowseKind.SEARCH,
                "Alne",
                0,
                40,
                search_scope=SearchScope.MOVIES,
            )
            shows = browse_document(
                client,
                CONFIG,
                BrowseKind.SEARCH,
                "Alne",
                0,
                40,
                search_scope=SearchScope.SHOWS,
            )
            season = browse_document(
                client,
                CONFIG,
                BrowseKind.SEARCH,
                "Alone S01E",
                0,
                40,
                search_scope=SearchScope.SHOWS,
            )
            episode_doc = browse_document(
                client,
                CONFIG,
                BrowseKind.SEARCH,
                "Alone S01E02",
                0,
                40,
                search_scope=SearchScope.SHOWS,
            )
        self.assertEqual([item["kind"] for item in movies["items"]], ["movie"])
        self.assertEqual([item["kind"] for item in shows["items"]], ["show"])
        self.assertEqual(season["total"], 2)
        self.assertEqual(
            [item["ratingKey"] for item in season["items"]], [EP1, EP2]
        )
        self.assertTrue(all("S01" in item["subtitle"] for item in season["items"]))
        self.assertTrue(all(item["playable"] for item in season["items"]))
        self.assertEqual(
            [item["ratingKey"] for item in episode_doc["items"]], [EP2]
        )

    def test_episode_browser_filters_codes_titles_and_filtered_pages(self):
        client = FakeClient(
            {
                "IncludeItemTypes=Episode": items(
                    episode(
                        EP4,
                        "Test Series",
                        series_id=SHOW,
                        season=4,
                        index=1,
                        title="Fourth One",
                        created=NOW,
                    ),
                    episode(
                        EP3,
                        "Test Series",
                        series_id=SHOW,
                        season=4,
                        index=2,
                        title="Fourth Two",
                        created=NOW,
                    ),
                    episode(
                        EP1,
                        "Test Series",
                        series_id=SHOW,
                        season=3,
                        index=1,
                        title="Third One",
                        created=NOW,
                    ),
                    episode(
                        EP2,
                        "Test Series",
                        series_id=SHOW,
                        season=3,
                        index=2,
                        title="Searchable Target",
                        created=NOW,
                    ),
                )
            }
        )
        with (
            mock.patch.object(browse_module, "utc_now", return_value=NOW),
            mock.patch.object(browse_module.shutil, "which", return_value=None),
        ):
            episode_doc = browse_document(
                client, CONFIG, BrowseKind.EPISODES, "s04e01", 0, 40, SHOW
            )
            season_page = browse_document(
                client, CONFIG, BrowseKind.EPISODES, "S03E", 1, 1, SHOW
            )
            title = browse_document(
                client, CONFIG, BrowseKind.EPISODES, "srch trgt", 0, 40, SHOW
            )
        self.assertEqual(episode_doc["total"], 1)
        self.assertEqual(
            [item["ratingKey"] for item in episode_doc["items"]], [EP4]
        )
        self.assertEqual(season_page["total"], 2)
        self.assertEqual(
            [item["ratingKey"] for item in season_page["items"]], [EP2]
        )
        self.assertEqual([item["ratingKey"] for item in title["items"]], [EP2])

    def test_season_browser_lists_seasons_under_a_show(self):
        client = FakeClient(
            {
                "IncludeItemTypes=Season": items(
                    season(SEASON2, "Season 2", index=2, leaf_count=8, unplayed=2),
                    season(SEASON1, "Season 1", index=1, leaf_count=10, unplayed=10),
                )
            }
        )
        with mock.patch.object(browse_module, "utc_now", return_value=NOW):
            document = browse_document(
                client, CONFIG, BrowseKind.SEASONS, "", 0, 40, SHOW
            )
        self.assertEqual(document["kind"], "seasons")
        self.assertEqual(
            [item["ratingKey"] for item in document["items"]], [SEASON1, SEASON2]
        )
        self.assertEqual(document["items"][0]["kind"], "season")
        self.assertFalse(document["items"][0]["playable"])
        self.assertEqual(document["items"][0]["showKey"], SHOW)
