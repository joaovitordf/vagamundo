import { createCvPickerState, pickNextCvKeyword } from './cv-area-picker.util';
import { CvAreaItem } from '../../core/models/vaga.model';

describe('pickNextCvKeyword', () => {
  it('returns null when no valid areas are provided', () => {
    const state = createCvPickerState();
    expect(pickNextCvKeyword([], state, '')).toBeNull();
    expect(pickNextCvKeyword([{ id: 'empty', keywords: [] }], state, '')).toBeNull();
  });

  it('cycles through all profile keywords before repeating and formats Meu perfil badge', () => {
    const areas: CvAreaItem[] = [
      { id: 'perfil-kw-1', label: 'Python', keywords: ['Python'] },
      { id: 'perfil-kw-2', label: 'Angular', keywords: ['Angular'] },
      { id: 'perfil-kw-3', label: 'FastAPI', keywords: ['FastAPI'] },
    ];
    let state = createCvPickerState();
    const firstCycle: string[] = [];

    for (let i = 0; i < 3; i++) {
      const res = pickNextCvKeyword(areas, state, firstCycle[firstCycle.length - 1] || '', 'profile');
      expect(res).not.toBeNull();
      firstCycle.push(res!.keyword);
      expect(res!.badgeText).toBe(`Meu perfil: ${res!.areaLabel}`);
      state = res!.state;
    }

    expect(new Set(firstCycle)).toEqual(new Set(['Python', 'Angular', 'FastAPI']));
    expect(state.queue.length).toBe(0);

    // Next cycle never repeats the immediately preceding item when >1 keywords exist
    const nextRes = pickNextCvKeyword(areas, state, firstCycle[2], 'profile');
    expect(nextRes).not.toBeNull();
    expect(nextRes!.keyword).not.toBe(firstCycle[2]);
  });

  it('drops deleted keywords from an existing queue when list changes', () => {
    const initial: CvAreaItem[] = [
      { id: 'perfil-kw-1', label: 'Python', keywords: ['Python'] },
      { id: 'perfil-kw-2', label: 'Legacy', keywords: ['Legacy'] },
    ];
    const first = pickNextCvKeyword(initial, createCvPickerState(), '', 'profile');
    expect(first).not.toBeNull();

    const updated: CvAreaItem[] = [
      { id: 'perfil-kw-1', label: 'Python', keywords: ['Python'] },
    ];
    const second = pickNextCvKeyword(updated, first!.state, first!.keyword, 'profile');
    expect(second?.keyword).toBe('Python');
  });
});
