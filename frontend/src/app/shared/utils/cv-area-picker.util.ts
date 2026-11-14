import { CvAreaItem, CvAreasSource } from '../../core/models/vaga.model';

export interface CvAreaPickerState {
  queue: CvAreaItem[];
  lastPickedId: string | null;
}

export interface CvAreaPickResult {
  keyword: string;
  badgeText: string;
  areaLabel: string;
  state: CvAreaPickerState;
}

export function createCvPickerState(): CvAreaPickerState {
  return { queue: [], lastPickedId: null };
}

/**
 * Picks the next keyword from CV areas using a non-repeating Fisher-Yates cycle.
 * Returns null if there are no drawable keywords.
 */
export function pickNextCvKeyword(
  areas: CvAreaItem[],
  prevState: CvAreaPickerState,
  currentFilterText: string,
  source: CvAreasSource = 'fallback',
): CvAreaPickResult | null {
  const validAreas = (areas || []).filter((area) =>
    Array.isArray(area?.keywords) && area.keywords.some((k) => String(k || '').trim().length > 0),
  );
  if (validAreas.length === 0) {
    return null;
  }

  let queue = prevState.queue.filter((item) => validAreas.some((v) => v.id === item.id));
  if (queue.length === 0) {
    queue = [...validAreas];
    for (let i = queue.length - 1; i > 0; i--) {
      const j = Math.floor(Math.random() * (i + 1));
      [queue[i], queue[j]] = [queue[j], queue[i]];
    }
    if (queue.length > 1 && queue[0].id === prevState.lastPickedId) {
      const swapIdx = 1 + Math.floor(Math.random() * (queue.length - 1));
      [queue[0], queue[swapIdx]] = [queue[swapIdx], queue[0]];
    }
  }

  const picked = queue.shift();
  if (!picked) {
    return null;
  }

  const candidates = (picked.keywords || [])
    .map((k) => String(k || '').trim())
    .filter(Boolean);
  const current = String(currentFilterText || '').trim().toLowerCase();
  const pool = candidates.filter((k) => k.toLowerCase() !== current);
  const keyword = (pool.length ? pool[Math.floor(Math.random() * pool.length)] : candidates[0]) || '';
  const areaLabel = picked.label || picked.title || keyword;
  const badgePrefix = source === 'profile' ? 'Meu perfil' : 'Área CV';

  return {
    keyword,
    areaLabel,
    badgeText: `${badgePrefix}: ${areaLabel}`,
    state: {
      queue,
      lastPickedId: picked.id,
    },
  };
}
