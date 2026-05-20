/**
 * cinema-promotion-dashboard / dashboard.js
 * --------------------------------------------------
 * 데이터(data.js)를 받아 화면을 렌더링하는 로직.
 */

// ============ UTILS ============
const fmt = (n) => n.toLocaleString('ko-KR');
const truncate = (str, n = 20) => (str && str.length > n) ? str.substr(0, n-1) + '...' : str;

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
function openDetail(movieTitle) {
  const modal = document.getElementById('detail-modal');
  if (!modal) return;
  document.getElementById('modal-title').textContent = movieTitle;

  // 샘플 데이터 (실제로는 영화별로 다른 데이터를 로드해야 함)
  document.getElementById('modal-dday').textContent = 'D-17';
  document.getElementById('modal-genre').textContent = '코미디 / 액션';
  document.getElementById('modal-pos').textContent = '5,791';
  document.getElementById('modal-neg').textContent = '134';
  document.getElementById('modal-sent-desc').textContent = '비율 43.2:1 · 긍정 98% (중립 제외)';
  document.getElementById('modal-volume').innerHTML = '324<span class="unit">건</span>';

  const insights = [
    'YouTube 누적 10M뷰 돌파 (2,419만 뷰 기록 중)',
    '오늘의 TOP 컨텐츠: 배우 비하인드 영상 (좋아요 119개)',
    '전일 대비 긍정적 키워드 유입 15% 증가'
  ];
  document.getElementById('modal-insights').innerHTML = insights.map(i => `<li>${i}</li>`).join('');

  const keywords = [
    {n: '강동원', v: 211}, {n: '엄태구', v: 154}, {n: '비하인드', v: 89},
    {n: '코미디', v: 77}, {n: '롯데시네마', v: 45}, {n: '포스터', v: 32}
  ];
  document.getElementById('modal-keyword-grid').innerHTML = keywords.map(k => `
    <span class="kw-pill">${k.n} <strong>${k.v}</strong></span>
  `).join('');

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

async function loadChainPromotions(opts) {
  const tbody = document.getElementById(opts.tbodyId);
  const note = document.getElementById(opts.noteId);
  if (!tbody) return null;
  try {
    const res = await fetch(opts.jsonPath, { cache: 'no-store' });
    if (!res.ok) throw new Error('HTTP ' + res.status);
    const data = await res.json();
    const movies = data.movies || [];
    const num = (n) => `<span class="pcount ${n ? '' : 'zero'}">${n || '—'}</span>`;
    if (movies.length === 0) {
      tbody.innerHTML = `<tr><td colspan="5" class="promo-empty">${opts.emptyMsg}</td></tr>`;
    } else {
      tbody.innerHTML = movies.map(m => {
        const c = m.counts;
        const total = c.coupon + c.stage + c.goods + c.etc;
        return `
          <tr>
            <td class="movie"><span class="name" title="${m.title}">${truncate(m.title)}</span></td>
            <td>${num(c.coupon)}</td>
            <td>${num(c.stage)}</td>
            <td>${num(c.goods)}</td>
            <td><strong class="pcount">${total}</strong> <span class="chip ${opts.chipClass} on">${opts.chipLabel}</span></td>
          </tr>`;
      }).join('');
    }
    if (note) {
      const ts = data.fetchedAt ? data.fetchedAt.slice(0, 16).replace('T', ' ') : '';
      const un = (data.unmatched || []).length;
      note.textContent = `※ 출처: ${data.source || '데이터 공급원'} · 수집 ${ts} · 미매칭 이벤트 ${un}건`;
    }
    return data;
  } catch (e) {
    tbody.innerHTML = `<tr><td colspan="5" class="promo-empty">${opts.emptyMsg}</td></tr>`;
    if (note) note.textContent = '';
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
      // 프로모션 좌석 — 무대인사 상영관 좌석 합계 (체인 크롤러가 promoSeats 로 제공)
      const promoSeats = chains.reduce(
        (s, m) => s + ((m && m.promoSeats) || 0), 0);
      return {
        movieCd: bk.movieCd, title: bk.title, rate: bk.rate,
        audience: bk.audience || 0,
        coupons: sum('coupon'), stage: sum('stage'), goods: sum('goods'),
        promoSeats: promoSeats,
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
    loadChainPromotions({
      jsonPath: 'assets/data/promotions_lotte.json',
      tbodyId: 'lotte-promo', noteId: 'lotte-promo-note',
      chipClass: 'chip-lotte', chipLabel: 'LOTTE',
      emptyMsg: '롯데 데이터 없음',
    }),
    loadChainPromotions({
      jsonPath: 'assets/data/promotions_megabox.json',
      tbodyId: 'megabox-promo', noteId: 'megabox-promo-note',
      chipClass: 'chip-mega', chipLabel: 'MEGABOX',
      emptyMsg: '메가박스 데이터 없음',
    }),
    loadChainPromotions({
      jsonPath: 'assets/data/promotions_cgv.json',
      tbodyId: 'cgv-promo', noteId: 'cgv-promo-note',
      chipClass: 'chip-cgv', chipLabel: 'CGV',
      emptyMsg: 'CGV 데이터 없음',
    }),
    loadChainPromotions({
      jsonPath: 'assets/data/promotions_cineq.json',
      tbodyId: 'cineq-promo', noteId: 'cineq-promo-note',
      chipClass: 'chip-cineq', chipLabel: 'CINEQ',
      emptyMsg: '씨네큐 데이터 없음',
    })
  ]);
  await buildAnalysisMatrix(resBo, resBk, resLt, resMg, resCg, resCq);
}

document.addEventListener('DOMContentLoaded', init);
