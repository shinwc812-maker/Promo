/**
 * cinema-promotion-dashboard / dashboard.js
 * --------------------------------------------------
 * 데이터(data.js)를 받아 화면을 렌더링하는 로직.
 */

// ============ UTILS ============
const fmt = (n) => n.toLocaleString('ko-KR');
const truncate = (str, n = 20) => (str && str.length > n) ? str.substr(0, n-1) + '...' : str;

// 이벤트명에서 '영화 제목'이 든 []·<> 괄호를 통째로 제거한다.
// 상세 모달은 이미 영화별로 묶여 있어 제목 반복이 길어 이벤트 구분을 방해함.
// [CGV회원시사]·[신한카드] 같은 비(非)제목 태그는 그대로 둔다.
const _normKey = (s) => (s || '').replace(/[^0-9a-z가-힣]/gi, '').toLowerCase();
function cleanEventName(name, movieTitle) {
  if (!name) return name;
  const nt = _normKey(movieTitle);
  if (!nt) return name;
  const out = name.replace(/[\[<]([^\[\]<>]*)[\]>]/g, (m, inner) => {
    const nb = _normKey(inner);
    // 괄호 내용이 '제목 자체'(같음·잘린 앞부분·구두점 차이·제목+꼬리)일 때만 제거.
    // 제목을 단순 '포함'만 하는 더 긴 프로그램명(예: '인사이드 더 플레이 : 군체')은 유지.
    if (nb && Math.min(nb.length, nt.length) >= 2 &&
        (nt.startsWith(nb) || nb.startsWith(nt) || nt.includes(nb))) {
      return '';                 // 영화 제목 괄호 → 제거
    }
    return m;                     // 그 외 태그 → 유지
  });
  return out.replace(/\s+/g, ' ').trim();
}

const pad2 = (n) => String(n).padStart(2, '0');
const now = new Date();
const ts = `${now.getFullYear()}.${pad2(now.getMonth()+1)}.${pad2(now.getDate())} ` +
           `${['일','월','화','수','목','금','토'][now.getDay()]}요일 ${pad2(now.getHours())}:${pad2(now.getMinutes())}`;

const reportDateEl = document.getElementById('report-date');
if (reportDateEl) reportDateEl.textContent = ts.toUpperCase().replace('요일',' ').replace(/(\d{4})\.(\d{2})\.(\d{2})/, '$1.$2.$3');
const lastSyncEl = document.getElementById('last-sync');
if (lastSyncEl) lastSyncEl.textContent = `${pad2(now.getHours())}:${pad2(now.getMinutes())}:${pad2(now.getSeconds())}`;
const next = new Date(now.getTime() + 60000);
const nextRefreshEl = document.getElementById('next-refresh');
if (nextRefreshEl) nextRefreshEl.textContent = `${pad2(next.getHours())}:${pad2(next.getMinutes())}:${pad2(next.getSeconds())}`;

// ============ RANK PANELS ============
function renderRanks(targetId, data, valueKey, deltaKey, valueFormat) {
  const container = document.getElementById(targetId);
  if (!container || !Array.isArray(data)) return;
  container.innerHTML = data.map(d => {
    const v = valueFormat(d[valueKey]);
    const delta = d[deltaKey];
    let dClass = 'delta';
    let dHtml = delta;
    if (delta === 'NEW') {
      dClass = 'delta new';
      dHtml = 'NEW';
    } else if (delta && delta.startsWith('+')) {
      dClass = 'delta up';
    } else if (delta && delta.startsWith('-')) {
      dClass = 'delta down';
    }
    return `
      <div class="rank-row">
        <span class="rank ${d.rank <= 3 ? 'top' : ''}">${pad2(d.rank)}</span>
        <span class="title clickable-title" title="${d.title}" onclick="openDetail('${d.title}')">${truncate(d.title)}</span>
        <span class="metric">${v}</span>
        <span class="${dClass}">${dHtml}</span>
      </div>`;
  }).join('');
}

// ============ MODAL LOGIC ============
// 로드된 데이터 전역 저장 — openDetail 에서 영화별 4사 프로모션 조회
const DATA = { booking: null, boxoffice: null,
               cgv: null, lotte: null, megabox: null, cineq: null };

// 개봉일(openDt) → D-day 표기. 개봉 후면 '개봉 N일차', 전이면 'D-N'
function ddayText(openDt) {
  if (!openDt) return '';
  const open = new Date(openDt + 'T00:00:00+09:00');
  const today = new Date();
  const diff = Math.floor((today - open) / 86400000);
  if (diff === 0) return 'D-DAY (개봉일)';
  if (diff > 0) return `개봉 ${diff + 1}일차 (D+${diff})`;
  return `개봉 D-${Math.abs(diff)}`;
}

// 영화명 → {movieCd, title, openDt, genre} (booking 우선, boxoffice 보조)
function resolveMovie(title) {
  const bk = (DATA.booking?.bookingRate || []).find(m => m.title === title);
  if (bk) return { movieCd: bk.movieCd, title: bk.title, openDt: bk.openDt, genre: bk.genre };
  const bo = (DATA.boxoffice?.boxOffice || []).find(m => m.title === title);
  if (bo) return { movieCd: bo.movieCd, title: bo.title, openDt: null, genre: bo.genre };
  return null;
}

// 4사 프로모션 상세 테이블 HTML 생성
function buildPromoDetail(movieCd, movieTitle) {
  const chains = [
    { key: 'cgv',     label: 'CGV',   data: DATA.cgv },
    { key: 'lotte',   label: '롯데',  data: DATA.lotte },
    { key: 'mega',    label: '메가',  data: DATA.megabox },
    { key: 'cineq',   label: '씨네큐', data: DATA.cineq },
  ];
  let tSeats = 0, tStage = 0, tCoupon = 0, tGoods = 0, tTheaters = 0, tIssued = 0, anyEvent = false;
  let rows = '';

  chains.forEach(ch => {
    const movie = (ch.data?.movies || []).find(m => m.movieCd === movieCd);
    const events = movie?.events || [];
    const stage  = events.filter(e => e.type === 'stage');
    const coupon = events.filter(e => e.type === 'coupon');
    const goods  = events.filter(e => e.type === 'goods');
    tStage += stage.length; tCoupon += coupon.length; tGoods += goods.length;
    stage.forEach(e => { if (typeof e.seats === 'number') tSeats += e.seats; });
    goods.forEach(e => { if (typeof e.theaters === 'number') tTheaters += e.theaters; });
    coupon.forEach(e => { if (typeof e.issued === 'number') tIssued += e.issued; });

    const n = Math.max(stage.length, coupon.length, goods.length);
    if (n === 0) {
      rows += `<tr class="chain-start empty-chain">
        <td class="chain-label"><span class="chip chip-${ch.key} on">${ch.label}</span></td>
        <td class="evt none" colspan="6">진행 이벤트 없음</td></tr>`;
      return;
    }
    anyEvent = true;
    for (let i = 0; i < n; i++) {
      const s = stage[i], c = coupon[i], g = goods[i];
      const seatVal = s
        ? (typeof s.seats === 'number' && s.seats > 0 ? fmt(s.seats) + '석' : '미공개')
        : '';
      const theaterVal = g
        ? (typeof g.theaters === 'number' && g.theaters > 0 ? g.theaters + '개관' : '미공개')
        : '';
      const issuedVal = c
        ? (typeof c.issued === 'number' && c.issued > 0 ? fmt(c.issued) + '매' : '미공개')
        : '';
      rows += `<tr class="${i === 0 ? 'chain-start' : ''}">
        ${i === 0 ? `<td class="chain-label" rowspan="${n}"><span class="chip chip-${ch.key} on">${ch.label}</span></td>` : ''}
        <td class="evt">${s ? truncate(cleanEventName(s.name, movieTitle), 24) : ''}</td>
        <td class="num">${seatVal}</td>
        <td class="evt">${c ? truncate(cleanEventName(c.name, movieTitle), 24) : ''}</td>
        <td class="num">${issuedVal}</td>
        <td class="evt">${g ? truncate(cleanEventName(g.name, movieTitle), 24) : ''}</td>
        <td class="num">${theaterVal}</td>
      </tr>`;
    }
  });

  const head = `<thead><tr>
      <th class="chain-col"></th>
      <th>무대인사·시사회</th><th class="num">좌석수</th>
      <th>쿠폰</th><th class="num">발행수</th>
      <th>굿즈·특전</th><th class="num">진행관수</th>
    </tr></thead>`;
  const total = `<tr class="total-row">
      <td class="chain-label">총합</td>
      <td class="evt">무대인사 ${tStage}건</td>
      <td class="num">${tSeats > 0 ? fmt(tSeats) + '석' : '미공개'}</td>
      <td class="evt">쿠폰 ${tCoupon}건</td>
      <td class="num">${tIssued > 0 ? fmt(tIssued) + '매' : '미공개'}</td>
      <td class="evt">굿즈 ${tGoods}건</td>
      <td class="num">${tTheaters > 0 ? tTheaters + '개관' : '미공개'}</td>
    </tr>`;
  if (!anyEvent && tStage + tCoupon + tGoods === 0) {
    return head + `<tbody><tr><td colspan="7" class="promo-empty">
      4사 진행 프로모션 없음 (실시간 예매율 TOP 10 매칭 기준)</td></tr></tbody>`;
  }
  return head + `<tbody>${rows}${total}</tbody>`;
}

function openDetail(movieTitle) {
  const modal = document.getElementById('detail-modal');
  if (!modal) return;
  const mv = resolveMovie(movieTitle);
  document.getElementById('modal-title').textContent = movieTitle;
  document.getElementById('modal-dday').textContent =
    mv && mv.openDt ? ddayText(mv.openDt) : '개봉일 미상';
  document.getElementById('modal-genre').textContent =
    (mv && mv.genre) ? mv.genre : '장르 미공개';

  const table = document.getElementById('promo-detail-table');
  if (mv) {
    table.innerHTML = buildPromoDetail(mv.movieCd, mv.title || movieTitle);
  } else {
    table.innerHTML = `<tbody><tr><td class="promo-empty">
      매칭되는 영화 데이터를 찾을 수 없습니다.</td></tr></tbody>`;
  }

  modal.classList.add('active');
  document.body.style.overflow = 'hidden';
}

function closeModal() {
  const modal = document.getElementById('detail-modal');
  if (modal) modal.classList.remove('active');
  document.body.style.overflow = 'auto';
}

window.onclick = function(event) {
  const modal = document.getElementById('detail-modal');
  if (event.target == modal) closeModal();
}

// ============ UTILS FOR MATRIX ============
function cellVal(val, isRate=false) {
  const display = isRate ? val.toFixed(1) + '%' : fmt(val);
  return `<span class="val">${display}</span>`;
}

// ============ DATA FETCHING ============

async function loadBooking() {
  const tagEl = document.getElementById('bk-time');
  try {
    const res = await fetch('assets/data/booking.json', { cache: 'no-store' });
    if (!res.ok) throw new Error('HTTP ' + res.status);
    const data = await res.json();
    renderRanks('booking', data.bookingRate, 'rate', 'delta', v => v.toFixed(1) + '%');
    if (tagEl && data.fetchedAt) tagEl.textContent = data.fetchedAt.slice(11, 16) + ' 수집';
    return data;
  } catch (e) {
    renderRanks('booking', typeof bookingRate !== 'undefined' ? bookingRate : [], 'rate', 'delta', v => v.toFixed(1) + '%');
    if (tagEl) tagEl.textContent = '실시간 · 목업';
    return null;
  }
}

async function loadBoxOffice() {
  const tagEl = document.getElementById('bo-date');
  try {
    const res = await fetch('assets/data/boxoffice.json', { cache: 'no-store' });
    if (!res.ok) throw new Error('HTTP ' + res.status);
    const data = await res.json();
    renderRanks('boxoffice', data.boxOffice, 'audience', 'change', v => fmt(v));
    if (tagEl && data.targetDt) {
      const d = data.targetDt;
      tagEl.textContent = `${d.slice(4, 6)}.${d.slice(6, 8)} 기준`;
    }
    return data;
  } catch (e) {
    renderRanks('boxoffice', typeof boxOffice !== 'undefined' ? boxOffice : [], 'audience', 'change', v => fmt(v));
    if (tagEl) tagEl.textContent = '일별 · 목업';
    return null;
  }
}

// 체인 프로모션 JSON 로드 (매트릭스 + 영화 상세 모달이 사용).
// 메인 화면 체인별 표는 제거됨 — 데이터만 가져온다.
async function loadChainData(jsonPath) {
  try {
    const res = await fetch(jsonPath, { cache: 'no-store' });
    if (!res.ok) throw new Error('HTTP ' + res.status);
    return await res.json();
  } catch (e) {
    console.error('[chain] 로드 실패:', jsonPath, e);
    return null;
  }
}

// ============ INTEGRATED MATRIX ============
// 예매율 TOP 10 을 기준으로 4사(롯데·메가박스·CGV·씨네큐) 프로모션 건수를 병합.
// 쿠폰·무대인사·굿즈는 진행 이벤트 '건수' 기준. (좌석 수는 수집 불가로 미포함)
async function buildAnalysisMatrix(rBo, rBk, rLt, rMg, rCg, rCq) {
  const matrixBody = document.getElementById('matrix');
  if (!matrixBody) return;
  try {
    const bookingList = rBk?.bookingRate || (typeof bookingRate !== 'undefined' ? bookingRate : []);
    if (!bookingList.length) throw new Error('표시할 예매율 데이터가 없습니다.');

    const pick = (res, cd) => (res?.movies || []).find(m => m.movieCd === cd);

    const integrated = bookingList.map(bk => {
      const chains = [pick(rLt, bk.movieCd), pick(rMg, bk.movieCd),
                      pick(rCg, bk.movieCd), pick(rCq, bk.movieCd)];
      const sum = (key) => chains.reduce(
        (s, m) => s + ((m && m.counts && m.counts[key]) || 0), 0);
      // 프로모션 좌석 = 무대인사·시사회·GV 좌석(promoSeats) + 쿠폰 발행 매수(issued).
      // 굿즈는 단위가 달라(진행관수) 제외.
      const stageSeats = chains.reduce(
        (s, m) => s + ((m && m.promoSeats) || 0), 0);
      const couponIssued = chains.reduce((s, m) => s + ((m && m.events || [])
        .filter(e => e.type === 'coupon')
        .reduce((a, e) => a + (typeof e.issued === 'number' ? e.issued : 0), 0)), 0);
      return {
        movieCd: bk.movieCd, title: bk.title, rate: bk.rate,
        audience: bk.audience || 0,
        coupons: sum('coupon'), stage: sum('stage'), goods: sum('goods'),
        promoSeats: stageSeats + couponIssued,
      };
    });

    // 해당 항목 이벤트가 있는 체인만 칩 활성화
    const chainBadges = (movieCd, type) => {
      const on = [];
      [[rCg, 'CGV'], [rLt, 'LOTTE'], [rMg, 'MEGA'], [rCq, 'CINEQ']].forEach(([res, label]) => {
        const m = pick(res, movieCd);
        if (m && m.counts && m.counts[type] > 0) on.push(label);
      });
      if (!on.length) return '';
      return `<span class="chains">${on.map(l =>
        `<span class="chip chip-${l.toLowerCase()} on">${l}</span>`).join('')}</span>`;
    };

    matrixBody.innerHTML = integrated.map(p => {
      const seatRatio = p.audience > 0 ? (p.promoSeats / p.audience) * 100 : 0;
      return `
        <tr>
          <td class="movie">
            <span class="name clickable-title" title="${p.title}" onclick="openDetail('${p.title}')">${truncate(p.title)}</span>
          </td>
          <td class="rate">${cellVal(p.rate, true)}</td>
          <td>${cellVal(p.audience)}</td>
          <td>${cellVal(p.promoSeats)}</td>
          <td class="seat-ratio"><span class="val">${seatRatio.toFixed(1)}%</span></td>
          <td>${cellVal(p.coupons)}${chainBadges(p.movieCd, 'coupon')}</td>
          <td>${cellVal(p.stage)}${chainBadges(p.movieCd, 'stage')}</td>
          <td>${cellVal(p.goods)}${chainBadges(p.movieCd, 'goods')}</td>
        </tr>`;
    }).join('');
  } catch (e) {
    console.error('[matrix] 통합 실패:', e);
    matrixBody.innerHTML = `<tr><td colspan="8" class="promo-empty">데이터 구성 오류: ${e.message}</td></tr>`;
  }
}

// ============ INITIALIZE ============
async function init() {
  const [resBk, resBo, resLt, resMg, resCg, resCq] = await Promise.all([
    loadBooking(),
    loadBoxOffice(),
    loadChainData('assets/data/promotions_lotte.json'),
    loadChainData('assets/data/promotions_megabox.json'),
    loadChainData('assets/data/promotions_cgv.json'),
    loadChainData('assets/data/promotions_cineq.json'),
  ]);
  // openDetail 모달이 참조할 전역 데이터 저장
  DATA.booking = resBk; DATA.boxoffice = resBo;
  DATA.lotte = resLt; DATA.megabox = resMg; DATA.cgv = resCg; DATA.cineq = resCq;
  await buildAnalysisMatrix(resBo, resBk, resLt, resMg, resCg, resCq);
}

document.addEventListener('DOMContentLoaded', init);
