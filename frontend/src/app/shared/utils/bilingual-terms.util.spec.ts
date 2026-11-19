import {
  expandTermBilingually,
  isUniversalSearchTerm,
  normalizeBilingualKey,
  shouldRequestAiTermExpansion,
} from './bilingual-terms.util';

describe('bilingual-terms.util', () => {
  it('expands Portuguese and English domain terms bidirectionally regardless of accents', () => {
    const cvPt = expandTermBilingually('Visão Computacional', 'both');
    expect(cvPt.terms).toEqual(['Visão Computacional', 'Computer Vision']);
    expect(cvPt.addedVariant).toBe('Computer Vision');
    expect(cvPt.matchedInDictionary).toBeTrue();

    const cvNoAccent = expandTermBilingually('visao computacional', 'en');
    expect(cvNoAccent.terms).toEqual(['Computer Vision']);

    const cvFromEn = expandTermBilingually('Computer Vision', 'both');
    expect(cvFromEn.terms).toEqual(['Computer Vision', 'Visão Computacional']);

    const cvPtOnly = expandTermBilingually('Computer Vision', 'pt');
    expect(cvPtOnly.terms).toEqual(['Visão Computacional']);
  });

  it('recognizes universal tech/business terms without requesting AI expansion', () => {
    expect(isUniversalSearchTerm('Python')).toBeTrue();
    expect(isUniversalSearchTerm('OpenCV')).toBeTrue();
    expect(isUniversalSearchTerm('FastAPI')).toBeTrue();
    expect(isUniversalSearchTerm('ERP')).toBeTrue();
    expect(shouldRequestAiTermExpansion('Python')).toBeFalse();
    expect(shouldRequestAiTermExpansion('Visão Computacional')).toBeFalse();
  });

  it('requests AI expansion only for unknown non-universal terms and respects cached overrides', () => {
    expect(shouldRequestAiTermExpansion('Engenharia Florestal')).toBeTrue();
    expect(shouldRequestAiTermExpansion('(Python OR Rust)')).toBeFalse();

    const overrides = {
      [normalizeBilingualKey('Engenharia Florestal')]: { en: 'Forestry Engineering', pt: null },
    };
    expect(shouldRequestAiTermExpansion('Engenharia Florestal', overrides)).toBeFalse();

    const expanded = expandTermBilingually('Engenharia Florestal', 'both', overrides);
    expect(expanded.terms).toEqual(['Engenharia Florestal', 'Forestry Engineering']);
    expect(expanded.addedVariant).toBe('Forestry Engineering');
    expect(expanded.matchedInDictionary).toBeFalse();
  });
});
