"""
라인망가 앱 (LINE マンガ Android) ADB 크롤러 에이전트

특징:
- ADB + uiautomator dump로 안드로이드 앱에서 직접 크롤링
- 브라우저 불필요 (Playwright 미사용)
- 3열 그리드 레이아웃, 위치 기반 순위 결정
- 今日の人気ランキング (총합) 페이지 크롤링
- すべて + 장르별 탭 수집 (キャンペーン, ￥0パス 제외)
"""

import asyncio
import shutil
import subprocess
import xml.etree.ElementTree as ET
import os
import logging
from typing import List, Dict, Any, Optional, Tuple

from crawler.agents.base_agent import CrawlerAgent, AgentResult

logger = logging.getLogger('crawler.agents.linemanga_app')

# ADB 경로 자동 탐지
ADB_PATH = (
    shutil.which('adb')
    or (os.path.isfile('/opt/homebrew/bin/adb') and '/opt/homebrew/bin/adb')
    or (os.path.isfile('/usr/local/bin/adb') and '/usr/local/bin/adb')
    or 'adb'
)

# 앱 패키지
PACKAGE = 'jp.naver.linemanga.android'

# 성별 필터 (랭킹 페이지 상단 오른쪽)
GENDER_FILTERS = [
    {'key': '', 'name': '総合', 'label': '종합'},
    {'key': '女性', 'name': '女性', 'label': '여성'},
    {'key': '男性', 'name': '男性', 'label': '남성'},
]

# 콘텐츠 영역 Y좌표 경계 (스크린샷 기반 실측)
# 상태바(0-77) + 헤더(108-171) + 탭바(190-314) + 성별필터(314-435) = 435부터 그리드
CONTENT_TOP_Y = 435     # 그리드 콘텐츠 시작 (탭/헤더 아래)
CONTENT_BOTTOM_Y = 2107 # 그리드 콘텐츠 끝 (하단 네비바 위)

# 수집할 장르 탭 목록 (탭 순서대로)
GENRE_TABS = [
    {'key': '', 'tab_name': 'すべて', 'label': '전체'},
    {'key': '恋愛', 'tab_name': '恋愛', 'label': '연애'},
    {'key': 'ファンタジー・SF', 'tab_name': 'ファンタジー･SF', 'label': '판타지/SF'},
    {'key': 'ミステリー・ホラー', 'tab_name': 'ミステリー･ホラー', 'label': '미스터리/호러'},
    {'key': 'ヒューマンドラマ', 'tab_name': 'ヒューマンドラマ', 'label': '휴먼드라마'},
    {'key': 'バトル・アクション', 'tab_name': 'バトル･アクション', 'label': '배틀/액션'},
    {'key': '裏社会・アングラ', 'tab_name': '裏社会･アングラ', 'label': '뒷세계'},
    {'key': 'コメディ・ギャグ', 'tab_name': 'コメディ･ギャグ', 'label': '코미디/개그'},
    {'key': 'スポーツ', 'tab_name': 'スポーツ', 'label': '스포츠'},
    {'key': '歴史・時代', 'tab_name': '歴史･時代', 'label': '역사/시대'},
]

# 제외할 탭
SKIP_TABS = {'キャンペーン', '￥0パス', '新着', 'オリジナル', '雑誌', '小説･ラノベ', 'その他'}

# 팝업/다이얼로그 닫기 버튼 후보 (우선순위 순)
POPUP_CLOSE_TEXTS = [
    '閉じる', 'とじる',                                    # 닫기
    '×', '✕', '✖',                                        # X 버튼
    'スキップ', 'SKIP',                                    # 스킵
    '後で', 'あとで', '後で読む', '今はしない', '今はやらない',  # 나중에
    'キャンセル', 'いいえ',                                # 취소/거부
    '同意する', 'OK',                                      # 동의/확인 (앱 사용 필수 다이얼로그)
]

# 팝업 의심 키워드 — 화면에 이 중 하나라도 보이면 팝업/이벤트 화면으로 판단
POPUP_HINT_KEYWORDS = [
    '次回から表示しない',           # 다음부터 표시 안함 체크박스 (확실한 팝업 신호)
    'MissionEvent', 'ミッション',    # 미션 이벤트 (5/3 사고 케이스)
    'おすすめマンガ',                # 추천만화 미션
    'ポイント獲得', 'ポイ活',         # 포인트 적립
    '今すぐ確認', 'プレゼント',       # 프로모션
    'ログインボーナス', '報酬を受け取る', # 로그인 보너스/보상
    'クーポン', 'ガチャ',             # 쿠폰/가챠
    '後日還元',                      # 환원
    'お知らせ',                      # 공지 다이얼로그
]



class LinemangaAppAgent(CrawlerAgent):
    """라인망가 앱 ADB 크롤러 에이전트"""

    def __init__(self):
        super().__init__(
            platform_id='linemanga_app',
            platform_name='라인망가 (앱)',
            url=''  # 앱이라 URL 없음
        )
        self.genre_results = {}
        self.device_id = None

    # ===== ADB 헬퍼 메서드 =====

    def _run_adb(self, cmd: str, timeout: int = 15) -> str:
        """ADB 명령 실행"""
        full_cmd = f'{ADB_PATH} shell {cmd}'
        try:
            result = subprocess.run(
                full_cmd, shell=True, capture_output=True, text=True, timeout=timeout
            )
            return result.stdout.strip()
        except subprocess.TimeoutExpired:
            self.logger.warning(f"ADB timeout: {cmd}")
            return ''
        except Exception as e:
            self.logger.error(f"ADB error: {e}")
            return ''

    def _check_device(self) -> bool:
        """ADB 디바이스 연결 확인 (데몬 자동 시작 + 재시도)"""
        import time
        for attempt in range(3):
            try:
                # ADB 서버 시작 (이미 실행 중이면 무시됨)
                subprocess.run(
                    f'{ADB_PATH} start-server', shell=True, capture_output=True, text=True, timeout=15
                )
                result = subprocess.run(
                    f'{ADB_PATH} devices', shell=True, capture_output=True, text=True, timeout=10
                )
                lines = result.stdout.strip().split('\n')
                for line in lines[1:]:  # 첫 줄 "List of devices attached" 스킵
                    if '\tdevice' in line:
                        self.device_id = line.split('\t')[0]
                        return True
                if attempt < 2:
                    self.logger.info(f"  📱 ADB 디바이스 대기 중... ({attempt+1}/3)")
                    time.sleep(5)
            except Exception:
                if attempt < 2:
                    time.sleep(5)
        return False

    def _tap(self, x: int, y: int):
        """화면 좌표 탭"""
        self._run_adb(f'input tap {x} {y}')

    def _swipe(self, x1: int, y1: int, x2: int, y2: int, duration: int = 300):
        """스와이프"""
        self._run_adb(f'input swipe {x1} {y1} {x2} {y2} {duration}')

    def _swipe_up(self, short: bool = False):
        """화면 위로 스크롤 (랭킹 더 보기). short=True이면 짧은 스크롤 (끝 부분용)"""
        if short:
            self._swipe(540, 1400, 540, 800, 400)
        else:
            self._swipe(540, 1800, 540, 600, 400)

    def _swipe_tabs_left(self):
        """탭 바를 왼쪽으로 스크롤 (더 많은 탭 보기)"""
        self._swipe(900, 258, 100, 258, 300)

    def _swipe_tabs_right(self):
        """탭 바를 오른쪽으로 스크롤 (처음 탭으로 돌아가기)"""
        self._swipe(100, 258, 900, 258, 300)

    def _dump_ui(self, local_path: str = '/tmp/lm_app_ui.xml') -> Optional[ET.Element]:
        """UI 트리 덤프 & 파싱"""
        try:
            self._run_adb('uiautomator dump /sdcard/ui.xml')
            subprocess.run(
                f'{ADB_PATH} pull /sdcard/ui.xml {local_path}',
                shell=True, capture_output=True, timeout=10
            )
            tree = ET.parse(local_path)
            return tree.getroot()
        except Exception as e:
            self.logger.error(f"UI dump failed: {e}")
            return None

    def _find_element_bounds(self, root: ET.Element, text: str) -> Optional[Tuple[int, int, int, int]]:
        """텍스트로 UI 요소의 bounds 찾기 (공백 무시)"""
        for node in root.iter('node'):
            node_text = node.get('text', '').strip()
            node_desc = node.get('content-desc', '').strip()
            if text in (node_text, node_desc):
                bounds = node.get('bounds', '')
                try:
                    parts = bounds.replace('[', '').replace(']', ',').split(',')
                    return int(parts[0]), int(parts[1]), int(parts[2]), int(parts[3])
                except:
                    pass
        return None

    def _tap_center(self, bounds: Tuple[int, int, int, int]):
        """bounds 중앙을 탭"""
        x = (bounds[0] + bounds[2]) // 2
        y = (bounds[1] + bounds[3]) // 2
        self._tap(x, y)

    def _press_back(self):
        """안드로이드 BACK 키 — 모달/팝업 닫기 범용 폴백"""
        self._run_adb('input keyevent KEYCODE_BACK')

    def _collect_all_texts(self, root: ET.Element) -> List[str]:
        """현재 화면의 모든 UI 텍스트(text + content-desc) 수집 — 휴리스틱 판단용"""
        texts = []
        for node in root.iter('node'):
            t = node.get('text', '').strip()
            d = node.get('content-desc', '').strip()
            if t:
                texts.append(t)
            if d and d != t:
                texts.append(d)
        return texts

    def _looks_like_popup(self, root: ET.Element) -> bool:
        """현재 화면이 팝업/이벤트 다이얼로그로 의심되는지 판정"""
        joined = ' '.join(self._collect_all_texts(root))
        return any(kw in joined for kw in POPUP_HINT_KEYWORDS)

    # ===== 스크린샷 & 썸네일 =====

    def _capture_screenshot(self, local_path: str = '/tmp/lm_app_screen.png'):
        """스크린샷 캡처 → PIL Image 반환"""
        try:
            self._run_adb('screencap -p /sdcard/screen.png')
            subprocess.run(
                f'{ADB_PATH} pull /sdcard/screen.png {local_path}',
                shell=True, capture_output=True, timeout=10
            )
            from PIL import Image as PILImage
            return PILImage.open(local_path)
        except Exception as e:
            self.logger.warning(f"Screenshot failed: {e}")
            return None

    @staticmethod
    def _parse_bounds(bounds_str: str) -> Optional[Tuple[int, int, int, int]]:
        """'[x1,y1][x2,y2]' 형식의 bounds 문자열 파싱"""
        try:
            parts = bounds_str.replace('[', '').replace(']', ',').split(',')
            return int(parts[0]), int(parts[1]), int(parts[2]), int(parts[3])
        except (ValueError, IndexError):
            return None

    def _parse_items_with_bounds(self, root: ET.Element) -> List[Dict[str, Any]]:
        """
        XML 구조 기반으로 랭킹 아이템 파싱 (구조적 접근).

        알고리즘:
        1. content-desc="ranking level" 뱃지 노드를 모두 찾음
        2. 뱃지의 부모 → 부모의 부모 = 아이템 컨테이너 (clickable View)
        3. 컨테이너의 첫 번째 큰 자식 View = 썸네일 bounds
        4. 컨테이너 하위 TextView 중 작품명 추출

        Returns:
            [{title, thumb_bounds: (x1,y1,x2,y2), item_bounds: (x1,y1,x2,y2)}, ...]
        """
        # parent map 빌드 (ElementTree는 부모 참조가 없으므로)
        parent_map = {child: parent for parent in root.iter() for child in parent}

        items = []
        seen_containers = set()  # 중복 방지 (같은 컨테이너에서 여러 뱃지 가능)

        for node in root.iter('node'):
            desc = node.get('content-desc', '').strip()
            if desc != 'ranking level':
                continue

            # 뱃지 → 부모 → 조부모 (아이템 컨테이너)
            badge_parent = parent_map.get(node)
            if badge_parent is None:
                continue
            container = parent_map.get(badge_parent)
            if container is None:
                continue

            # 컨테이너 bounds
            container_bounds_str = container.get('bounds', '')
            container_bounds = self._parse_bounds(container_bounds_str)
            if container_bounds is None:
                continue

            cx1, cy1, cx2, cy2 = container_bounds
            container_w = cx2 - cx1
            container_h = cy2 - cy1

            # 중복 컨테이너 스킵
            container_key = f"{cx1},{cy1},{cx2},{cy2}"
            if container_key in seen_containers:
                continue
            seen_containers.add(container_key)

            # 너무 작은 컨테이너 스킵 (하단 네비바 아이템 등)
            # 높이 150 이상이면 부분적으로 보이는 아이템도 제목 추출 시도
            if container_w < 250 or container_h < 150:
                continue

            # 화면 밖 아이템 스킵 (약간의 여유 허용)
            if cy2 < CONTENT_TOP_Y or cy1 > CONTENT_BOTTOM_Y + 200:
                continue

            # 썸네일 bounds: 컨테이너 직계/간접 자식 중 큰 View 찾기
            thumb_bounds = None
            self._find_thumbnail_bounds(container, container_bounds, thumb_bounds_result := [])
            if thumb_bounds_result:
                thumb_bounds = thumb_bounds_result[0]

            # 타이틀: 뱃지 y좌표 아래에 있는 첫 번째 의미있는 TextView
            badge_bounds = self._parse_bounds(node.get('bounds', ''))
            badge_y = badge_bounds[3] if badge_bounds else cy1 + 400

            title = ''
            self._find_title_text(container, badge_y, title_result := [])
            if title_result:
                title = title_result[0]

            if not title:
                continue

            items.append({
                'title': title,
                'thumb_bounds': thumb_bounds,
                'item_bounds': container_bounds,
            })

        # 위→아래, 왼→오른 정렬
        items.sort(key=lambda it: (it['item_bounds'][1], it['item_bounds'][0]))
        return items

    def _find_thumbnail_bounds(self, container, container_bounds, result: list):
        """컨테이너 내에서 썸네일 View bounds 찾기 (재귀 탐색)"""
        cx1, cy1, cx2, cy2 = container_bounds
        container_w = cx2 - cx1

        for child in container:
            child_bounds = self._parse_bounds(child.get('bounds', ''))
            if child_bounds is None:
                continue

            bx1, by1, bx2, by2 = child_bounds
            bw = bx2 - bx1
            bh = by2 - by1

            # 썸네일: 컨테이너와 같은 너비(±30px), 높이 150~500px (부분 아이템도 허용)
            if abs(bw - container_w) <= 30 and 150 <= bh <= 500:
                result.append(child_bounds)
                return

            # 재귀: 내부 컨테이너 탐색
            if len(child) > 0:
                self._find_thumbnail_bounds(child, container_bounds, result)
                if result:
                    return

    def _find_title_text(self, container, badge_y: int, result: list):
        """뱃지 아래에서 작품 제목 TextView 찾기 (재귀 탐색)"""
        for child in container:
            # TextView에서 텍스트 추출
            text = child.get('text', '').strip()
            if text:
                child_bounds = self._parse_bounds(child.get('bounds', ''))
                if child_bounds:
                    _, ty1, _, _ = child_bounds
                    # 뱃지 아래에 있는 텍스트 = 제목 (첫 번째만)
                    if ty1 >= badge_y - 20 and len(text) >= 1:
                        # 에피소드 정보/무료 정보 제외
                        if not any(kw in text for kw in ['話無料', '冊無料', 'CMみて', '¥0パス', '集計']):
                            # 순수 숫자 제외
                            stripped = text.replace(',', '').replace('.', '').replace(' ', '')
                            try:
                                int(stripped)
                                pass  # 숫자 → 스킵
                            except ValueError:
                                result.append(text)
                                return

            # 재귀
            if len(child) > 0:
                self._find_title_text(child, badge_y, result)
                if result:
                    return

    def _crop_from_xml_bounds(self, screenshot, thumb_bounds) -> str:
        """
        XML bounds로 정확히 크롭 → base64 data URL.

        - thumb_bounds: (x1, y1, x2, y2) from XML UIAutomator dump
        - 상단 60%만 크롭하여 순위 번호 오버레이 제거
          (라인망가 앱은 썸네일 하단에 큰 순위 번호를 렌더링)
        - 화면 내 가시 영역만 클램핑 (CONTENT_TOP_Y ~ CONTENT_BOTTOM_Y)
        - 가시 비율 35% 미만이면 스킵 (부분 크롭 방지)
        - numpy std < 15 이면 스킵 (단색/UI 요소)
        - 150×200 JPEG 리사이즈
        """
        import base64
        from io import BytesIO
        import numpy as np

        if screenshot is None or thumb_bounds is None:
            return ''

        x1, y1, x2, y2 = thumb_bounds
        full_height = y2 - y1

        # 상단 60%만 사용 — 하단 40%에 렌더링되는 순위 번호 오버레이 제거
        y2 = y1 + int(full_height * 0.60)

        # 화면 내 가시 영역 클램핑
        visible_top = max(y1, CONTENT_TOP_Y)
        visible_bottom = min(y2, CONTENT_BOTTOM_Y)

        if visible_bottom <= visible_top:
            return ''

        visible_height = visible_bottom - visible_top
        cropped_height = y2 - y1  # 60% 적용 후 높이

        # 가시 비율 35% 미만 → 스킵 (너무 많이 잘린 썸네일)
        if cropped_height > 0 and visible_height / cropped_height < 0.35:
            return ''

        try:
            crop = screenshot.crop((x1, visible_top, x2, visible_bottom))
            crop_rgb = crop.convert('RGB')

            # 이미지 품질 검증: 단색/UI 요소 거부
            arr = np.array(crop_rgb)
            if arr.std() < 15:
                return ''

            # 150x200 리사이즈 + JPEG 압축
            crop_resized = crop_rgb.resize((150, 200))
            buf = BytesIO()
            crop_resized.save(buf, format='JPEG', quality=65)
            b64 = base64.b64encode(buf.getvalue()).decode('ascii')
            return f"data:image/jpeg;base64,{b64}"
        except Exception:
            return ''

    def _fetch_cdn_thumbnails(self, titles: List[str]) -> Dict[str, str]:
        """
        웹 CDN에서 깨끗한 원본 썸네일을 일괄 수집.

        1순위: DB에서 linemanga(웹) thumbnail_url 조회 → CDN 다운로드
        2순위: manga.line.me 검색으로 CDN URL 획득 → 다운로드

        Returns: {title: "data:image/jpeg;base64,...", ...}
        """
        import base64 as b64_mod
        import urllib.request
        import urllib.parse
        import re
        from io import BytesIO
        from PIL import Image as PILImage

        result = {}
        if not titles:
            return result

        # --- 1순위: DB에서 linemanga 웹 썸네일 URL 일괄 조회 ---
        remaining = list(titles)
        cdn_urls = {}  # title → cdn_url

        try:
            from crawler.db import get_db_connection
            conn = get_db_connection()
            cur = conn.cursor()
            cur.execute("""
                SELECT title, thumbnail_url FROM works
                WHERE platform = 'linemanga'
                AND title IN %s
                AND thumbnail_url IS NOT NULL AND thumbnail_url != ''
            """, (tuple(remaining),))
            for row in cur.fetchall():
                cdn_urls[row[0]] = row[1]
            cur.close()
            conn.close()
            self.logger.info(f"  🌐 DB에서 웹 썸네일 {len(cdn_urls)}개 매칭")
        except Exception as e:
            self.logger.warning(f"  ⚠️ DB 웹 썸네일 조회 실패: {e}")

        remaining = [t for t in remaining if t not in cdn_urls]

        # --- 2순위: JSON API 검색으로 CDN URL 획득 ---
        import json as json_mod
        import unicodedata

        search_found = 0
        title_suffixes = [
            '【電子単行本版】', '【電子単行本】', '【単行本版】', '【単話版】',
            '【単話】', '【コミックス版】', '【連載版】', '【タテヨミ】',
            '【分冊版】', '【御無礼合本版】',
            '（コミック）', '（連載版）', '（分冊版）', '@COMIC',
        ]

        def _clean(t):
            c = t
            for sfx in title_suffixes:
                c = c.replace(sfx, '')
            c = re.sub(r'[［\[](.*?)[］\]]', '', c)
            c = re.sub(r'[（\(](話売り|分冊版)[）\)]', '', c)
            c = re.sub(r'\s*(分冊版|超合本版|愛蔵版|新装版)$', '', c)
            c = re.sub(r'\s*コミック版.*$', '', c)
            return c.replace('\u3000', ' ').strip().strip('「」')

        def _norm(s):
            return unicodedata.normalize('NFKC', s).lower().replace(' ', '').replace('\u3000', '')

        for title in remaining:
            clean = _clean(title)
            short = clean.split('～')[0].split('~')[0].strip() if ('～' in clean or '~' in clean) else clean
            search_words = list(dict.fromkeys([clean, short, title]))  # 중복 제거, 순서 유지

            found = False
            for word in search_words:
                if found or not word or len(word) < 2:
                    break
                try:
                    encoded = urllib.parse.quote(word)
                    api_url = f"https://manga.line.me/api/search_product/list?word={encoded}"
                    req = urllib.request.Request(api_url, headers={'User-Agent': 'Mozilla/5.0'})
                    resp = urllib.request.urlopen(req, timeout=5)
                    data = json_mod.load(resp)

                    rows = data.get('result', {}).get('rows', [])
                    nc = _norm(clean)
                    for item in rows:
                        iname = item.get('name', '')
                        ni = _norm(iname)
                        if (nc == ni or nc in ni or ni in nc
                            or (len(nc) >= 5 and nc[:8] == ni[:8])):
                            cdn = item.get('thumbnail', '')
                            if cdn:
                                cdn_urls[title] = cdn
                                search_found += 1
                                found = True
                                break
                except Exception:
                    pass

        if search_found:
            self.logger.info(f"  🔍 API 검색으로 {search_found}개 추가 매칭")

        # --- CDN URL → base64 다운로드 & 변환 ---
        for title, cdn_url in cdn_urls.items():
            try:
                req = urllib.request.Request(cdn_url, headers={'User-Agent': 'Mozilla/5.0'})
                resp = urllib.request.urlopen(req, timeout=5)
                img_data = resp.read()

                img = PILImage.open(BytesIO(img_data)).convert('RGB')
                img_resized = img.resize((150, 200))
                buf = BytesIO()
                img_resized.save(buf, format='JPEG', quality=70)
                b64 = b64_mod.b64encode(buf.getvalue()).decode('ascii')
                result[title] = f"data:image/jpeg;base64,{b64}"
            except Exception:
                pass

        self.logger.info(f"  🖼️ CDN 썸네일 {len(result)}/{len(titles)}개 수집 완료")
        return result

    def _switch_gender_on_home(self, gender_name: str) -> bool:
        """
        홈 화면에서 성별 필터 전환.

        흐름:
        1. 홈에서 스크롤하며 "今日の人気ランキング" 섹션 찾기
        2. 옆의 현재 필터(총합/남성/여성) 텍스트 탭
        3. 바텀시트 드롭다운에서 원하는 성별 선택
        """
        import time, re

        # 홈 탭 더블탭으로 맨 위로 이동
        root = self._dump_ui()
        if root:
            home_bounds = self._find_element_bounds(root, 'おすすめ')
            if not home_bounds:
                home_bounds = self._find_element_bounds(root, 'home')
            if home_bounds:
                self._tap_center(home_bounds)
                time.sleep(0.5)
                self._tap_center(home_bounds)
                time.sleep(1)

        # 스크롤하며 "今日の人気ランキング" 섹션 찾기
        for scroll_i in range(8):
            root = self._dump_ui()
            if root is None:
                return False

            # 랭킹 섹션의 성별 필터 버튼 찾기
            # "今日の人気ランキング" 근처에 있는 総合/男性/女性 텍스트
            ranking_title = self._find_element_bounds(root, '今日の人気ランキング')
            if ranking_title:
                # 같은 높이(y좌표 비슷)에 있는 필터 버튼 찾기
                rt_y = ranking_title[1]  # y1 좌표

                filter_bounds = None
                for label in ['総合', '男性', '女性']:
                    b = self._find_element_bounds(root, label)
                    if b:
                        by = b[1]  # y1 좌표
                        # 랭킹 제목과 같은 높이 (±100px)
                        if abs(by - rt_y) < 100:
                            filter_bounds = b
                            break

                if filter_bounds:
                    # 필터 버튼 탭 → 드롭다운 열기
                    self._tap_center(filter_bounds)
                    time.sleep(2)

                    # 드롭다운에서 원하는 성별 선택
                    root = self._dump_ui()
                    if root is None:
                        return False

                    target = self._find_element_bounds(root, gender_name)
                    if not target:
                        self.logger.warning(f"  ⚠️ 드롭다운에서 '{gender_name}' 을 찾을 수 없음")
                        self._run_adb('input keyevent KEYCODE_BACK')
                        time.sleep(1)
                        return False

                    self._tap_center(target)
                    time.sleep(3)
                    self.logger.info(f"  ✅ 성별 필터 '{gender_name}' 선택 완료")
                    return True

            self._swipe_up()
            time.sleep(1)

        self.logger.warning("  ⚠️ 홈에서 랭킹 섹션을 찾을 수 없음")
        return False

    # ===== 크롤링 로직 =====

    def _collect_tab_rankings(self, max_scrolls: int = 25, max_items: int = 100) -> List[Dict[str, Any]]:
        """
        현재 탭에서 스크롤하며 전체 랭킹 수집 (제목만 파싱).
        썸네일은 save()에서 CDN 일괄 수집.

        Returns:
            [{rank, title, genre, url, thumbnail_url}, ...]
        """
        import time
        all_titles = []
        seen_titles = set()
        no_new_count = 0

        for scroll_i in range(max_scrolls + 1):
            if scroll_i == 0:
                time.sleep(2.5)  # 탭 전환 후 콘텐츠 로딩 대기
            elif no_new_count > 0:
                time.sleep(2.5)
            else:
                time.sleep(1)

            root = self._dump_ui(f'/tmp/lm_app_scroll_{scroll_i}.xml')
            if root is None:
                break

            items = self._parse_items_with_bounds(root)
            new_count = 0

            # 첫 스크롤에서 아이템이 0이면 추가 대기 후 재시도
            if scroll_i == 0 and len(items) == 0:
                self.logger.debug("  첫 시도 아이템 0 → 3초 추가 대기 후 재시도")
                time.sleep(3)
                root = self._dump_ui(f'/tmp/lm_app_scroll_{scroll_i}_retry.xml')
                if root is not None:
                    items = self._parse_items_with_bounds(root)

            for item in items:
                title = item['title']
                if title not in seen_titles:
                    seen_titles.add(title)
                    all_titles.append(title)
                    new_count += 1

            self.logger.debug(f"  Scroll {scroll_i}: {new_count} new, total {len(all_titles)}")

            if new_count == 0:
                no_new_count += 1
                if no_new_count >= 4:
                    break
            else:
                no_new_count = 0

            if len(all_titles) >= max_items:
                break

            if scroll_i < max_scrolls:
                use_short = no_new_count > 0 or len(all_titles) >= max_items - 15
                self._swipe_up(short=use_short)

        # 순위 할당 (수집 순서 = 순위)
        rankings = []
        for rank, title in enumerate(all_titles[:max_items], 1):
            rankings.append({
                'rank': rank,
                'title': title,
                'genre': '',
                'url': '',
                'thumbnail_url': '',
            })

        return rankings

    def _dismiss_popups(self, max_attempts: int = 10) -> int:
        """
        화면에 보이는 모든 팝업/이벤트 다이얼로그를 자동 닫기.

        전략 (순차):
          1. "次回から表示しない" 체크박스 발견 시 먼저 탭
          2. POPUP_CLOSE_TEXTS 의 닫기 버튼 텍스트 순차 시도
          3. 닫기 버튼 없지만 화면이 팝업으로 의심(POPUP_HINT_KEYWORDS) → BACK 키
          4. 직전과 화면 텍스트가 동일 (탭이 효과 없었음) → BACK 키
          5. 팝업 의심 안되고 진행 없음이 2회 연속 → 종료

        Returns: 처리한 팝업 개수
        """
        import time

        dismissed = 0
        prev_texts_hash = None
        no_progress = 0

        for popup_i in range(max_attempts):
            root = self._dump_ui()
            if root is None:
                time.sleep(1)
                continue

            all_texts = self._collect_all_texts(root)
            texts_hash = hash(tuple(sorted(all_texts)))
            screen_unchanged = (texts_hash == prev_texts_hash)
            prev_texts_hash = texts_hash

            joined = ' '.join(all_texts)
            is_popup = any(kw in joined for kw in POPUP_HINT_KEYWORDS)

            # 1) "次回から表示しない" 체크박스 먼저 처리
            dont_show = self._find_element_bounds(root, '次回から表示しない')
            if dont_show:
                self._tap_center(dont_show)
                time.sleep(0.5)

            # 2) 직전 탭이 효과 없었고 팝업이 의심됨 → 즉시 BACK
            if screen_unchanged and is_popup and popup_i > 0:
                self.logger.info(f"  🔙 팝업이 안 닫힘 → BACK 키 ({popup_i + 1})")
                self._press_back()
                time.sleep(2.0)
                dismissed += 1
                no_progress = 0
                continue

            # 3) 닫기 버튼 텍스트 순차 시도
            closed = False
            for close_text in POPUP_CLOSE_TEXTS:
                bounds = self._find_element_bounds(root, close_text)
                if bounds:
                    self.logger.info(f"  🔲 팝업 닫기 ({close_text}) ({popup_i + 1})")
                    self._tap_center(bounds)
                    time.sleep(2.0)
                    dismissed += 1
                    closed = True
                    no_progress = 0
                    break

            if closed:
                continue

            # 4) 닫기 버튼 없음 + 팝업 의심 → BACK 키
            if is_popup:
                self.logger.info(f"  🔙 팝업 의심 화면 → BACK 키 ({popup_i + 1})")
                self._press_back()
                time.sleep(2.0)
                dismissed += 1
                no_progress = 0
                continue

            # 5) 일반 화면 — 더 닫을 게 없음
            no_progress += 1
            if no_progress >= 2:
                break

        if dismissed > 0:
            self.logger.info(f"  ✅ {dismissed}개 팝업 처리 완료")
        return dismissed

    def _wake_screen(self):
        """폰 화면 깨우기 (화면 꺼져있거나 잠금 상태일 때)"""
        import time
        # 화면 상태 확인 (Dozing/Asleep = 꺼짐, Awake = 켜짐)
        state = self._run_adb('dumpsys power | grep mWakefulness')
        if 'Awake' not in state:
            self.logger.info("  📱 화면 깨우기...")
            self._run_adb('input keyevent KEYCODE_WAKEUP')
            time.sleep(2)
        # 잠금 해제: wm dismiss-keyguard (비밀번호/패턴 잠금도 해제)
        self._run_adb('wm dismiss-keyguard')
        time.sleep(1)
        # 스와이프도 시도 (dismiss-keyguard 실패 시 폴백)
        self._swipe(540, 2000, 540, 800, 300)
        time.sleep(1)
        # 한 번 더 확인 — 여전히 꺼져있으면 전원 버튼
        state2 = self._run_adb('dumpsys power | grep mWakefulness')
        if 'Awake' not in state2:
            self.logger.info("  📱 전원 버튼으로 재시도...")
            self._run_adb('input keyevent KEYCODE_POWER')
            time.sleep(2)
            self._run_adb('wm dismiss-keyguard')
            time.sleep(1)

    def _restart_app(self):
        """앱 종료 후 재실행 + 팝업 닫기"""
        import time

        self.logger.info("📱 라인망가 앱 재시작...")
        self._wake_screen()
        self._run_adb(f'am force-stop {PACKAGE}')
        time.sleep(2)
        self._run_adb(
            f'monkey -p {PACKAGE} -c android.intent.category.LAUNCHER 1'
        )
        time.sleep(10)  # 콜드 스타트/느린 네트워크 대비 10초 대기

        # 팝업 자동 닫기 (매일 3~5개 팝업 표시됨)
        self._dismiss_popups(max_attempts=10)

    def _enter_ranking_from_home(self) -> bool:
        """
        현재 홈 화면에서 "今日の人気ランキング" 을 찾아 탭 → 랭킹 페이지 진입.
        앱 재시작 없이 동작.
        """
        import time

        # 홈 탭 더블탭으로 맨 위로 이동
        root = self._dump_ui()
        if root is None:
            self.logger.error("  ❌ UI dump 실패 — 화면 상태 확인 필요")
            return False

        # 홈 화면 확인 (おすすめ 또는 하단 네비바 홈 아이콘)
        home_bounds = self._find_element_bounds(root, 'おすすめ')
        if not home_bounds:
            home_bounds = self._find_element_bounds(root, 'home')
        if not home_bounds:
            # 홈 버튼을 못 찾으면 팝업이 남아있을 수 있음
            self.logger.warning("  ⚠️ 홈 버튼 미발견 → 추가 팝업 확인")
            self._dismiss_popups(max_attempts=3)
            time.sleep(1)
            root = self._dump_ui()
            if root:
                home_bounds = self._find_element_bounds(root, 'おすすめ')
                if not home_bounds:
                    home_bounds = self._find_element_bounds(root, 'home')

        if home_bounds:
            self._tap_center(home_bounds)
            time.sleep(0.5)
            self._tap_center(home_bounds)
            time.sleep(1.5)

        # 스크롤하며 "今日の人気ランキング" 찾아 탭 (12회로 증가)
        for scroll_i in range(12):
            root = self._dump_ui()
            if root is None:
                time.sleep(1)
                continue

            ranking_bounds = self._find_element_bounds(root, '今日の人気ランキング')
            if ranking_bounds:
                self.logger.info("  '今日の人気ランキング' 발견 → 탭")
                self._tap_center(ranking_bounds)
                time.sleep(4)

                root = self._dump_ui()
                if root is None:
                    return False

                ranking_header = self._find_element_bounds(root, 'ランキング')
                if ranking_header:
                    self.logger.info("  ✅ 랭킹 페이지 도달")
                    return True

                self.logger.warning("  ⚠️ 랭킹 페이지 확인 실패, 재시도...")
                home_bounds = self._find_element_bounds(root, 'おすすめ')
                if home_bounds:
                    self._tap_center(home_bounds)
                    time.sleep(1)
                continue

            # 스크롤 도중 팝업이 늦게 떴는지 감지 — 떴으면 닫고 재시도
            # (5/3 사고: 미션 이벤트 팝업이 앱 시작 후 늦게 떠서 홈 스크롤 막음)
            if self._looks_like_popup(root):
                self.logger.info("  🔲 스크롤 중 팝업 감지 → 닫기 시도")
                self._dismiss_popups(max_attempts=5)
                time.sleep(1)
                continue

            self._swipe_up()
            time.sleep(1.5)

        # 실패 시 진단 로깅 — 현재 화면에 보이는 텍스트 목록
        self._log_visible_texts("홈 스크롤 실패")
        self.logger.error("❌ 랭킹 페이지를 찾을 수 없음")
        return False

    def _log_visible_texts(self, context: str = ""):
        """현재 화면에 보이는 UI 텍스트 목록을 로그에 출력 (진단용)"""
        root = self._dump_ui()
        if root is None:
            self.logger.warning(f"  📋 [{context}] UI dump 실패")
            return

        texts = []
        for node in root.iter('node'):
            text = node.get('text', '').strip()
            if text and len(text) < 80:
                texts.append(text)

        if texts:
            sample = texts[:15]
            self.logger.info(f"  📋 [{context}] 화면 텍스트: {sample}")
        else:
            self.logger.warning(f"  📋 [{context}] 화면에 텍스트 없음")

    def _navigate_to_ranking_page(self) -> bool:
        """앱 재시작 후 랭킹 페이지 진입."""
        self._restart_app()
        return self._enter_ranking_from_home()

    def _find_tab_bounds(self, root: ET.Element, tab_name: str) -> Optional[Tuple[int, int, int, int]]:
        """탭 이름으로 UI 요소 찾기 (부분 매칭 + 중점 문자 통일)"""
        # 중점 문자 통일 (・, ･, · 모두 매칭)
        def normalize_dots(s):
            return s.replace('・', '･').replace('·', '･')

        normalized_name = normalize_dots(tab_name)

        for node in root.iter('node'):
            node_text = node.get('text', '').strip()
            node_desc = node.get('content-desc', '').strip()

            for txt in (node_text, node_desc):
                if not txt:
                    continue
                normalized_txt = normalize_dots(txt)
                if normalized_txt == normalized_name or normalized_name in normalized_txt:
                    bounds = node.get('bounds', '')
                    try:
                        parts = bounds.replace('[', '').replace(']', ',').split(',')
                        return int(parts[0]), int(parts[1]), int(parts[2]), int(parts[3])
                    except:
                        pass
        return None

    def _scroll_to_top(self):
        """랭킹 리스트를 맨 위로 스크롤 (탭바 보이도록)"""
        import time
        for _ in range(15):
            self._swipe(540, 600, 540, 1800, 200)  # 빠른 스와이프 다운
            time.sleep(0.2)
        time.sleep(1.0)  # 스크롤 애니메이션 완료 대기

    def _is_tab_bar_visible(self, root) -> bool:
        """탭 바가 화면에 보이는지 확인 (y=200~300 영역에 탭 텍스트 존재)"""
        for node in root.iter('node'):
            txt = node.get('text', '').strip()
            if not txt:
                continue
            bounds = node.get('bounds', '')
            try:
                parts = bounds.replace('[', '').replace(']', ',').split(',')
                y1, y2 = int(parts[1]), int(parts[3])
                if 200 <= y1 <= 300 and 200 <= y2 <= 300:
                    if txt in ('すべて', '恋愛', 'キャンペーン', '新着', '￥0パス'):
                        return True
            except:
                pass
        return False

    def _navigate_to_tab(self, tab_name: str) -> bool:
        """
        탭 이름으로 특정 장르 탭 이동.
        먼저 페이지 상단으로 스크롤 후, 탭 바를 좌우 스크롤하며 찾음.
        """
        import time

        # 랭킹 리스트 수집 후 스크롤이 아래에 있으므로, 먼저 상단으로 복귀
        self._scroll_to_top()

        # 탭 바가 보이는지 확인 (안 보이면 추가 스크롤)
        root = self._dump_ui()
        if root is not None and not self._is_tab_bar_visible(root):
            self.logger.info("  탭 바 미확인 → 추가 스크롤")
            for _ in range(10):
                self._swipe(540, 600, 540, 1800, 200)
                time.sleep(0.2)
            time.sleep(1.0)

        # 먼저 현재 상태에서 탭 검색 (리셋 없이)
        root = self._dump_ui()
        if root is not None:
            bounds = self._find_tab_bounds(root, tab_name)
            if bounds:
                # 화면 가장자리에 걸쳐있으면 (보이는 너비 < 60px) 스크롤 후 재탐색
                bx1, _, bx2, _ = bounds
                if bx2 - bx1 < 60:
                    self._swipe_tabs_left()
                    time.sleep(0.8)
                    root = self._dump_ui()
                    if root is not None:
                        bounds = self._find_tab_bounds(root, tab_name)
                if bounds:
                    self._tap_center(bounds)
                    time.sleep(2)
                    return True

        # 탭 바를 맨 왼쪽으로 리셋 (오른쪽으로 4번 스크롤)
        for _ in range(4):
            self._swipe_tabs_right()
            time.sleep(0.3)
        time.sleep(0.8)

        # 왼쪽으로 스크롤하며 탭 찾기 (최대 10번)
        for scroll_i in range(10):
            time.sleep(1.0)
            root = self._dump_ui()
            if root is None:
                time.sleep(0.5)
                continue

            bounds = self._find_tab_bounds(root, tab_name)
            if bounds:
                # 화면 가장자리에 걸쳐있으면 한번 더 스크롤
                bx1, _, bx2, _ = bounds
                if bx2 - bx1 < 60:
                    self._swipe_tabs_left()
                    time.sleep(0.8)
                    root = self._dump_ui()
                    if root is not None:
                        bounds = self._find_tab_bounds(root, tab_name)
                if bounds:
                    self._tap_center(bounds)
                    time.sleep(2)
                    return True

            self._swipe_tabs_left()

        self.logger.warning(f"  ⚠️ 탭 '{tab_name}' 을 찾을 수 없음")
        return False

    # ===== CrawlerAgent 인터페이스 =====

    async def execute(self, browser=None) -> AgentResult:
        """
        ADB 기반 크롤링 실행 (browser 파라미터 무시).
        """
        self.logger.info(f"Starting {self.platform_name} crawler (ADB)")

        for attempt in range(self.max_retries):
            try:
                # 1. 디바이스 확인
                if not self._check_device():
                    return AgentResult(
                        success=False,
                        platform=self.platform_id,
                        error="ADB device not connected (skip)",
                        attempts=1
                    )
                self.logger.info(f"  📱 Device: {self.device_id}")

                import time

                # 2. 종합(기본) 랭킹 수집
                if not self._navigate_to_ranking_page():
                    raise Exception("Failed to navigate to ranking page")

                # 3. 성별 필터 × 장르 탭 크롤링
                all_rankings = None  # 종합 전체 (메인 데이터)

                for gender in GENDER_FILTERS:
                    gender_key = gender['key']
                    gender_name = gender['name']
                    gender_label = gender['label']

                    if gender_key:
                        # 여성/남성: 홈으로 돌아간 후 성별 전환 → 랭킹 재진입
                        self.logger.info(f"📱 [{gender_label}] 홈으로 복귀 → 필터 전환...")
                        self._run_adb('input keyevent KEYCODE_BACK')
                        time.sleep(2)

                        if not self._switch_gender_on_home(gender_name):
                            self.logger.warning(f"  ⚠️ [{gender_label}] 필터 전환 실패")
                            continue

                        # 성별 전환 후 앱 재시작 없이 랭킹 페이지 진입
                        if not self._enter_ranking_from_home():
                            self.logger.warning(f"  ⚠️ [{gender_label}] 랭킹 페이지 재진입 실패")
                            continue

                    # すべて 탭 크롤링
                    sub_key = gender_key  # '' or '女性' or '男性'
                    self.logger.info(f"📱 [{gender_label} 전체] 크롤링 중...")
                    if not self._navigate_to_tab('すべて'):
                        self.logger.warning(f"  ⚠️ [{gender_label} 전체] すべて 탭 이동 실패")
                        continue

                    time.sleep(2)
                    # 전체(すべて) 탭에서는 항상 썸네일 캡처
                    rankings = self._collect_tab_rankings()
                    self.genre_results[sub_key] = rankings
                    self.logger.info(f"  ✅ [{gender_label} 전체]: {len(rankings)}개 작품")

                    if gender_key == '':
                        all_rankings = rankings

                    # 장르별 탭 크롤링
                    for genre_info in GENRE_TABS[1:]:  # すべて 스킵
                        tab_name = genre_info['tab_name']
                        label = genre_info['label']
                        genre_key_part = genre_info['key']

                        # 복합 키: "女性:恋愛" 형태
                        if gender_key:
                            compound_key = f"{gender_key}:{genre_key_part}"
                        else:
                            compound_key = genre_key_part

                        self.logger.info(f"📱 [{gender_label}·{label}] 크롤링 중...")

                        try:
                            if self._navigate_to_tab(tab_name):
                                time.sleep(2)
                                tab_rankings = self._collect_tab_rankings()
                                self.genre_results[compound_key] = tab_rankings
                                self.logger.info(f"  ✅ [{gender_label}·{label}]: {len(tab_rankings)}개")
                            else:
                                self.genre_results[compound_key] = []
                                self.logger.warning(f"  ⚠️ [{gender_label}·{label}] 탭 이동 실패")
                        except Exception as e:
                            self.logger.warning(f"  ⚠️ [{gender_label}·{label}] 실패: {e}")
                            self.genre_results[compound_key] = []

                # 4. 데이터 검증
                if all_rankings is None:
                    raise Exception("종합 전체 데이터 수집 실패")

                if self.validate(all_rankings):
                    from datetime import datetime
                    date = datetime.now().strftime('%Y-%m-%d')
                    await self.save(date, all_rankings)

                    self.logger.info(
                        f"✅ {self.platform_name}: {len(all_rankings)}개 작품 수집 완료"
                    )
                    return AgentResult(
                        success=True,
                        platform=self.platform_id,
                        data=all_rankings,
                        attempts=attempt + 1
                    )
                else:
                    raise ValueError(f"Validation failed: {len(all_rankings)} items")

            except Exception as e:
                error_msg = str(e)
                self.logger.warning(
                    f"Attempt {attempt + 1}/{self.max_retries} failed: {error_msg}"
                )
                if attempt < self.max_retries - 1:
                    delay = self.retry_delays[attempt]
                    self.logger.info(f"Retrying in {delay} seconds...")
                    await asyncio.sleep(delay)
                else:
                    self.logger.error(
                        f"❌ {self.platform_name} 실패: {error_msg}"
                    )
                    return AgentResult(
                        success=False,
                        platform=self.platform_id,
                        error=error_msg,
                        attempts=attempt + 1
                    )

        return AgentResult(
            success=False,
            platform=self.platform_id,
            error="Unknown error",
            attempts=self.max_retries
        )

    async def crawl(self, browser=None) -> List[Dict[str, Any]]:
        """사용되지 않음 (execute()에서 직접 처리)"""
        return []

    def validate(self, data: List[Dict[str, Any]]) -> bool:
        """ADB 크롤링은 최소 5개 이상이면 유효"""
        if not data or len(data) < 5:
            self.logger.warning(f"Validation failed: only {len(data) if data else 0} items")
            return False
        for item in data:
            if 'rank' not in item or 'title' not in item:
                return False
        return True

    async def save(self, date: str, data: List[Dict[str, Any]]):
        """성별 × 장르별 전체 랭킹 저장 + CDN 썸네일 일괄 수집"""
        from crawler.db import save_rankings, backup_to_json, save_works_metadata

        # 종합 전체 랭킹 저장 + JSON 백업
        save_rankings(date, self.platform_id, data, sub_category='')
        works_meta = [
            {'title': item['title'], 'thumbnail_url': '',
             'url': '', 'genre': item.get('genre', ''), 'rank': item.get('rank')}
            for item in data
        ]
        if works_meta:
            save_works_metadata(self.platform_id, works_meta, date=date, sub_category='')
        backup_to_json(date, self.platform_id, data)

        # 나머지 모든 장르/성별 조합 저장
        for sub_key, rankings in self.genre_results.items():
            if sub_key == '' or not rankings:
                continue
            if ':' in sub_key:
                parts = sub_key.split(':', 1)
                label = f"{parts[0]}/{parts[1]}"
            else:
                label = sub_key

            save_rankings(date, self.platform_id, rankings, sub_category=sub_key)
            meta = [
                {'title': item['title'], 'thumbnail_url': '',
                 'url': '', 'genre': item.get('genre', ''), 'rank': item.get('rank')}
                for item in rankings
            ]
            if meta:
                save_works_metadata(self.platform_id, meta, date=date, sub_category=sub_key)
            self.logger.info(f"   💾 [{label}]: {len(rankings)}개 저장")

        # === CDN 썸네일 일괄 수집 & 저장 ===
        thumb_count = 0
        try:
            from crawler.db import save_thumbnail_base64, get_db_connection

            # 모든 탭에서 고유 제목 취합
            all_titles = set()
            for item in data:
                if item.get('title'):
                    all_titles.add(item['title'])
            for gk, rankings in self.genre_results.items():
                if rankings:
                    for item in rankings:
                        if item.get('title'):
                            all_titles.add(item['title'])

            # 이미 썸네일이 있는 작품 제외 (불필요한 재수집 방지)
            if all_titles:
                conn = get_db_connection()
                cur = conn.cursor()
                cur.execute("""
                    SELECT title FROM works
                    WHERE platform = %s AND title IN %s
                    AND thumbnail_base64 IS NOT NULL AND thumbnail_base64 != ''
                """, (self.platform_id, tuple(all_titles)))
                existing = {r[0] for r in cur.fetchall()}
                cur.close()
                conn.close()
                all_titles -= existing
                if existing:
                    self.logger.info(f"  ⏭️ 기존 썸네일 {len(existing)}개 스킵")

            if all_titles:
                self.logger.info(f"  🌐 CDN 썸네일 수집 시작 ({len(all_titles)}개 작품)...")
                cdn_thumbs = self._fetch_cdn_thumbnails(list(all_titles))

                for title, b64_data in cdn_thumbs.items():
                    if b64_data:
                        save_thumbnail_base64(self.platform_id, title, b64_data)
                        thumb_count += 1
        except Exception as e:
            self.logger.warning(f"  ⚠️ CDN 썸네일 수집/저장 실패: {e}")
        if thumb_count:
            self.logger.info(f"   🖼️ CDN 썸네일 {thumb_count}개 저장")


if __name__ == "__main__":
    import asyncio
    import time

    async def test():
        print("=" * 60)
        print("라인망가 앱 (ADB) 에이전트 테스트")
        print("=" * 60)

        agent = LinemangaAppAgent()

        # 디바이스 체크
        if not agent._check_device():
            print("❌ ADB 디바이스가 연결되지 않았습니다.")
            return

        print(f"📱 Device: {agent.device_id}")

        result = await agent.execute()

        print(f"\n✅ Success: {result.success}")
        print(f"📊 Count: {result.count}")

        if result.success and result.data:
            print(f"\n샘플 (1~10위):")
            for item in result.data[:10]:
                print(f"  {item['rank']}위: {item['title']}")

            print(f"\n장르별 결과:")
            for genre_info in GENRE_TABS:
                key = genre_info['key']
                label = genre_info['label']
                rankings = agent.genre_results.get(key, [])
                print(f"  [{label}]: {len(rankings)}개")
        else:
            print(f"\n❌ Error: {result.error}")

        print("\n" + "=" * 60)

    asyncio.run(test())
