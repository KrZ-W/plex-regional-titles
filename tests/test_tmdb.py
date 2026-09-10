from plex_regional_titles.models import Kind
from plex_regional_titles.sources.tmdb import TmdbSource, pick_translation
from tests.conftest import make_item


def tr(lang, region, **data):
    return {"iso_639_1": lang, "iso_3166_1": region, "data": data}


class FakeClient:
    def __init__(self, payloads):
        self.payloads = payloads
        self.calls = []

    def translations(self, kind, tmdb_id):
        self.calls.append((kind, tmdb_id))
        return self.payloads.get((kind, tmdb_id), [])


def test_pick_translation_movie_and_show():
    t = [
        tr("fr", "FR", title="Hugo Cabret", name="Show FR"),
        tr("fr", "CA", title="Hugo", name="Émission"),
        tr("en", "CA", title="Hugo EN"),
    ]
    assert pick_translation(t, "fr", ["CA"], Kind.MOVIE) == "Hugo"
    assert pick_translation(t, "fr", ["CA"], Kind.SHOW) == "Émission"
    assert pick_translation(t, "fr", ["FR", "CA"], Kind.MOVIE) == "Hugo Cabret"
    assert pick_translation(t, "fr", ["BE"], Kind.MOVIE) is None
    assert pick_translation([tr("fr", "CA", title="  ")], "fr", ["CA"], Kind.MOVIE) is None


def test_source_resolves_with_mocked_client(settings):
    client = FakeClient(
        {
            (Kind.MOVIE, "10"): [tr("fr", "CA", title="Hugo")],
            (Kind.SHOW, "20"): [tr("fr", "CA", name="La Série")],
        }
    )
    src = TmdbSource(settings, client=client)
    src.prepare()
    c = src.resolve(make_item("Hugo Cabret", tmdb="10"))
    assert c and c.title == "Hugo" and c.source == "tmdb" and c.authoritative
    s = src.resolve(make_item("The Show", tmdb="20", kind=Kind.SHOW))
    assert s and s.title == "La Série"
    assert src.resolve(make_item("X", tmdb="99")) is None
    assert src.resolve(make_item("X", tmdb=None)) is None
    # cached: second lookup does not call the client again
    src.resolve(make_item("Hugo Cabret", tmdb="10"))
    assert client.calls.count((Kind.MOVIE, "10")) == 1
    src.close()
