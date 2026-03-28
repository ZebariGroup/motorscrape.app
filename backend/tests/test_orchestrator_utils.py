from app.schemas import DealershipFound
from app.services.orchestrator_utils import dedupe_dealers_by_domain


def test_dedupe_dealers_by_domain_skips_same_name_and_address_alias_domains() -> None:
    dealers = [
        DealershipFound(
            name="Southgate Honda Powersports",
            place_id="1",
            address="15150 Eureka Rd, Southgate, MI 48195, USA",
            website="https://www.southgatehondapowersports.com/",
        ),
        DealershipFound(
            name="Southgate Honda Powersports",
            place_id="2",
            address="15150 Eureka Rd, Southgate, MI 48195, USA",
            website="https://www.genthehondapowersports.com/map-hours-directions-atvs-utvs-motorcycles-dealership--hours",
        ),
        DealershipFound(
            name="Rosenau Powersports",
            place_id="3",
            address="24732 Ford Rd, Dearborn Heights, MI 48127, USA",
            website="https://www.rosenaupowersports.net/",
        ),
    ]
    out = dedupe_dealers_by_domain(dealers)
    assert [d.website for d in out] == [
        "https://www.southgatehondapowersports.com/",
        "https://www.rosenaupowersports.net/",
    ]
