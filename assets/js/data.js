/**
 * cinema-promotion-dashboard / data.js
 * --------------------------------------------------
 * 임시 목업 데이터. 실제 운영 시 아래 출처에서 받아오도록 교체:
 *   - boxOffice    : KOFIC OpenAPI  · searchDailyBoxOfficeList
 *   - bookingRate  : KOBIS 실시간 예매율 페이지 스크래핑
 *   - promotions   : 4사 이벤트 페이지 크롤링 결과를 movieCd 기준 조인
 *
 * 영화 식별 키는 KOFIC `movieCd` 로 통일하는 것을 권장.
 */

const boxOffice = [
  { rank:1,  movieCd:'20259001', title:'서울의 봄밤',    audience:124583, change:'+12.3%' },
  { rank:2,  movieCd:'20259002', title:'검은 비',         audience:98421,  change:'-2.1%'  },
  { rank:3,  movieCd:'20259003', title:'외계인+인간',    audience:76234,  change:'+18.2%' },
  { rank:4,  movieCd:'20259004', title:'하루의 끝',       audience:65893,  change:'+5.8%'  },
  { rank:5,  movieCd:'20259005', title:'블루 아워',       audience:54128,  change:'-8.4%'  },
  { rank:6,  movieCd:'20259006', title:'프로젝트 H',      audience:42751,  change:'+24.1%' },
  { rank:7,  movieCd:'20259007', title:'겨울 항해',       audience:38192,  change:'+2.3%'  },
  { rank:8,  movieCd:'20259008', title:'마지막 약속',    audience:29456,  change:'-12.7%' },
  { rank:9,  movieCd:'20259009', title:'붉은 거리',       audience:21038,  change:'NEW'    },
  { rank:10, movieCd:'20259010', title:'달을 삼킨 자',   audience:18672,  change:'-3.5%'  },
];

const bookingRate = [
  { rank:1,  movieCd:'20259001', title:'서울의 봄밤',   rate:32.4, delta:'+1.2' },
  { rank:2,  movieCd:'20259003', title:'외계인+인간',   rate:18.7, delta:'+3.1' },
  { rank:3,  movieCd:'20259002', title:'검은 비',        rate:14.2, delta:'-0.8' },
  { rank:4,  movieCd:'20259004', title:'하루의 끝',      rate:9.8,  delta:'+0.5' },
  { rank:5,  movieCd:'20259006', title:'프로젝트 H',     rate:6.3,  delta:'+2.4' },
  { rank:6,  movieCd:'20259005', title:'블루 아워',      rate:5.1,  delta:'-1.1' },
  { rank:7,  movieCd:'20259007', title:'겨울 항해',      rate:3.8,  delta:'+0.2' },
  { rank:8,  movieCd:'20259008', title:'마지막 약속',   rate:2.4,  delta:'-0.6' },
  { rank:9,  movieCd:'20259009', title:'붉은 거리',      rate:1.9,  delta:'NEW'  },
  { rank:10, movieCd:'20259010', title:'달을 삼킨 자',  rate:1.2,  delta:'-0.3' },
];

// 영화별로 4사 합산한 프로모션 데이터
//   chains       : 각 체인 프로모션 진행 여부 (1/0)
//   coupons      : 4사 합산 쿠폰 발급 수량
//   stage        : 4사 합산 무대인사 횟수
//   seats        : 4사 합산 총 좌석 수
//   goodsVenues  : 굿즈 이벤트 진행 영화관 개소 수 (점유율 계산 제외, 참고용)
//   goodsBreak   : 체인별 진행 영화관 수 [CGV, LOTTE, MEGA, CINEQ]
//   rate         : 실시간 예매율 (%)
const promotions = [
  { movieCd:'20259001', title:'서울의 봄밤',   chains:{CGV:1, LOTTE:1, MEGA:1, CINEQ:1}, coupons:4820, stage:18, seats:142500, goodsVenues:78, goodsBreak:[28,24,19,7], rate:32.4 },
  { movieCd:'20259003', title:'외계인+인간',   chains:{CGV:1, LOTTE:1, MEGA:1, CINEQ:0}, coupons:3210, stage:9,  seats:98400,  goodsVenues:54, goodsBreak:[24,18,12,0], rate:18.7 },
  { movieCd:'20259002', title:'검은 비',        chains:{CGV:1, LOTTE:1, MEGA:1, CINEQ:1}, coupons:2980, stage:6,  seats:86200,  goodsVenues:41, goodsBreak:[15,12,10,4], rate:14.2 },
  { movieCd:'20259004', title:'하루의 끝',      chains:{CGV:1, LOTTE:0, MEGA:1, CINEQ:1}, coupons:1850, stage:4,  seats:54100,  goodsVenues:32, goodsBreak:[18,0,11,3],  rate:9.8  },
  { movieCd:'20259006', title:'프로젝트 H',     chains:{CGV:0, LOTTE:1, MEGA:1, CINEQ:0}, coupons:920,  stage:3,  seats:31200,  goodsVenues:18, goodsBreak:[0,10,8,0],   rate:6.3  },
  { movieCd:'20259005', title:'블루 아워',      chains:{CGV:1, LOTTE:1, MEGA:0, CINEQ:0}, coupons:1240, stage:2,  seats:42800,  goodsVenues:22, goodsBreak:[14,8,0,0],   rate:5.1  },
  { movieCd:'20259007', title:'겨울 항해',      chains:{CGV:0, LOTTE:1, MEGA:1, CINEQ:1}, coupons:780,  stage:2,  seats:28600,  goodsVenues:16, goodsBreak:[0,7,6,3],    rate:3.8  },
  { movieCd:'20259008', title:'마지막 약속',   chains:{CGV:1, LOTTE:0, MEGA:0, CINEQ:1}, coupons:540,  stage:1,  seats:19400,  goodsVenues:8,  goodsBreak:[5,0,0,3],    rate:2.4  },
  { movieCd:'20259009', title:'붉은 거리',      chains:{CGV:1, LOTTE:1, MEGA:0, CINEQ:0}, coupons:1620, stage:5,  seats:24800,  goodsVenues:36, goodsBreak:[22,14,0,0],  rate:1.9  },
  { movieCd:'20259010', title:'달을 삼킨 자',  chains:{CGV:0, LOTTE:0, MEGA:1, CINEQ:0}, coupons:310,  stage:0,  seats:12100,  goodsVenues:4,  goodsBreak:[0,0,4,0],    rate:1.2  },
];
