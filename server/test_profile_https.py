"""
프로필 사진 주소는 **https 로 올려 보낸다.**

카카오·네이버 CDN 이 http 주소를 준다. 사이트는 https 라 브라우저가
혼합 콘텐츠로 막아 사진이 깨진 네모로 뜬다(실측: 카카오 로그인 후 아바타).
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from serve import Handler                                     # noqa: E402

P = Handler._profile


def test_kakao_http_becomes_https():
    me = {"id": 123, "kakao_account": {"profile": {
        "nickname": "황민",
        "profile_image_url": "http://k.kakaocdn.net/dn/abc/img_640x640.jpg"}}}
    uid, name, img = P("kakao", me)
    assert uid == "123" and name == "황민"
    assert img == "https://k.kakaocdn.net/dn/abc/img_640x640.jpg"


def test_naver_http_becomes_https():
    me = {"response": {"id": "n1", "nickname": "민",
                       "profile_image": "http://phinf.pstatic.net/a.jpg"}}
    uid, name, img = P("naver", me)
    assert uid == "n1" and name == "민"
    assert img == "https://phinf.pstatic.net/a.jpg"


def test_https_is_left_alone():
    me = {"id": 1, "kakao_account": {"profile": {
        "profile_image_url": "https://k.kakaocdn.net/x.jpg"}}}
    assert P("kakao", me)[2] == "https://k.kakaocdn.net/x.jpg"


def test_no_photo_stays_empty():
    # 사진은 선택 동의다 — 거절하면 빈 문자열로 온다
    assert P("kakao", {"id": 1})[2] == ""
    assert P("naver", {"response": {"id": "n"}})[2] == ""


if __name__ == "__main__":
    test_kakao_http_becomes_https()
    test_naver_http_becomes_https()
    test_https_is_left_alone()
    test_no_photo_stays_empty()
    print("ok")
