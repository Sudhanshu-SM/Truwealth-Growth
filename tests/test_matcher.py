from radar.config import load_config
from radar.matcher import Matcher
from radar.models import Topic


def topic(topic_id, *keywords):
    return Topic(id=topic_id, name=topic_id, bucket="markets", keywords=keywords, angles=("explainer",))


def test_word_boundaries():
    m = Matcher([topic("ipo_buzz", "IPO")])
    assert m.match("Hippo sightings rise") == []
    assert m.match("LIC IPO opens today") == ["ipo_buzz"]


def test_short_all_caps_keywords_are_case_sensitive():
    m = Matcher([topic("sip", "SIP")])
    assert m.match("Take a sip of coffee") == []
    assert m.match("SIP inflows hit a record") == ["sip"]


def test_longer_keywords_are_case_insensitive():
    assert Matcher([topic("gold", "gold price")]).match("GOLD PRICE jumps") == ["gold"]


def test_devanagari_substring():
    assert Matcher([topic("market", "शेयर बाजार")]).match("आज शेयर बाजार में गिरावट") == ["market"]


def test_special_characters():
    m = Matcher([topic("fno", "F&O"), topic("us", "S&P 500")])
    assert m.match("SEBI tightens F&O rules") == ["fno"]
    assert m.match("S&P 500 falls 2%") == ["us"]


def test_real_topics_route_typical_headlines():
    m = Matcher(load_config().topics)
    assert "rbi_policy" in m.match("RBI keeps repo rate unchanged at 5.25%")
    assert "gold_price" in m.match("Gold rate today: yellow metal hits record high")
    assert "ipo_buzz" in m.match("J Infratech files IPO papers; eyes Rs 600 cr")
    assert "upi_payments" in m.match("नए UPI MDR नियम 15 अक्टूबर से लागू होंगे")
    assert m.match("Bangkok declares flood disaster in all 50 districts") == []
