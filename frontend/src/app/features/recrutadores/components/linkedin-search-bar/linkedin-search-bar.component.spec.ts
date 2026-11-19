import { ComponentFixture, TestBed, fakeAsync, tick } from '@angular/core/testing';
import { of, throwError } from 'rxjs';
import { ApiService } from '../../../../core/services/api.service';
import { RecruiterPost } from '../../../../core/models/vaga.model';
import {
  BILINGUAL_TERM_CACHE_KEY,
  LinkedinSearchBarComponent,
} from './linkedin-search-bar.component';

describe('LinkedinSearchBarComponent', () => {
  let fixture: ComponentFixture<LinkedinSearchBarComponent>;
  let component: LinkedinSearchBarComponent;
  let apiSpy: jasmine.SpyObj<ApiService>;

  beforeEach(async () => {
    localStorage.removeItem(BILINGUAL_TERM_CACHE_KEY);
    apiSpy = jasmine.createSpyObj<ApiService>('ApiService', [
      'pasteRecruiterPost',
      'pasteRecruiterPostsBatch',
      'expandRecruiterSearchTerm',
      'triageRecruiterPosts',
      'markRecruiterPostInterested',
      'dismissRecruiterPost',
    ]);
    apiSpy.expandRecruiterSearchTerm.and.returnValue(
      of({ ok: true, term: '', en: null, pt: null, source: 'none' })
    );
    apiSpy.triageRecruiterPosts.and.returnValue(
      of({
        ok: true,
        triaged: 0,
        active_jobs: 0,
        talent_pools_discarded: 0,
        not_a_job: 0,
        errors: 0,
        posts: [],
      })
    );
    apiSpy.markRecruiterPostInterested.and.returnValue(
      of({ ok: true, post_id: 1, job_id: 'job-1', url: '' })
    );
    apiSpy.dismissRecruiterPost.and.returnValue(of({ ok: true, id: 1 }));

    await TestBed.configureTestingModule({
      imports: [LinkedinSearchBarComponent],
      providers: [{ provide: ApiService, useValue: apiSpy }],
    }).compileComponents();

    fixture = TestBed.createComponent(LinkedinSearchBarComponent);
    component = fixture.componentInstance;
    fixture.detectChanges();
  });

  afterEach(() => {
    localStorage.removeItem(BILINGUAL_TERM_CACHE_KEY);
  });

  it('builds lean bilingual search strings reactively and resets manual overrides on filter changes', () => {
    component.filterText = 'Visão Computacional';
    component.jobAgeFilter = '7';
    fixture.detectChanges();

    expect(component.activeLinkedInQuery()).toBe(
      '("Visão Computacional" OR "Computer Vision") AND (vaga OR contratando OR hiring)'
    );
    expect(component.activeQueryHealth().level).toBe('optimal');
    expect(component.activeLinkedInUrl()).toContain('datePosted=%22past-week%22');
    expect(component.activeGoogleXRayUrl()).toContain('site%3Alinkedin.com%2Fposts');
    expect(component.addedVariantBadge()).toBe('+ Computer Vision');

    component.setLinkedInLanguageMode('en');
    fixture.detectChanges();
    expect(component.activeLinkedInQuery()).toBe('"Computer Vision" AND (hiring OR "open role")');

    component.setLinkedInLanguageMode('both');
    component.setLinkedInPreset('hiring_email');
    fixture.detectChanges();
    expect(component.activeLinkedInQuery()).toBe(
      '("Visão Computacional" OR "Computer Vision") AND (hiring OR contratando) AND (email OR "e-mail" OR "@gmail.com")'
    );
    expect(component.activeQueryHealth().level).toBe('optimal');
    expect((fixture.nativeElement as HTMLElement).textContent).toContain('Hiring + E-mail');

    component.onLinkedInQueryInput('Custom Boolean Query');
    expect(component.linkedInCustomQuery()).toBe('Custom Boolean Query');

    component.filterText = 'Java, Spring';
    expect(component.linkedInCustomQuery()).toBeNull();
    expect(component.activeLinkedInQuery()).toContain('(Java OR Spring)');
  });

  it('automatically expands unknown whitelabel terms with configured AI and caches the translation', fakeAsync(() => {
    apiSpy.expandRecruiterSearchTerm.and.returnValue(
      of({ ok: true, term: 'Engenharia Florestal', en: 'Forestry Engineering', pt: null, source: 'ai' })
    );

    component.filterText = 'Engenharia Florestal';
    fixture.detectChanges();

    expect(component.activeLinkedInQuery()).toBe('"Engenharia Florestal" AND (vaga OR contratando OR hiring)');
    expect(apiSpy.expandRecruiterSearchTerm).not.toHaveBeenCalled();

    tick(500);
    fixture.detectChanges();

    expect(apiSpy.expandRecruiterSearchTerm).toHaveBeenCalledTimes(1);
    expect(apiSpy.expandRecruiterSearchTerm).toHaveBeenCalledWith('Engenharia Florestal');
    expect(component.activeLinkedInQuery()).toBe(
      '("Engenharia Florestal" OR "Forestry Engineering") AND (vaga OR contratando OR hiring)'
    );
    expect(localStorage.getItem(BILINGUAL_TERM_CACHE_KEY)).toContain('Forestry Engineering');
  }));

  it('auto-evaluates pasted LinkedIn posts inline and supports Me interessa and Descartar directly', () => {
    const importedPost: RecruiterPost = {
      id: 901,
      portal: 'linkedin_post',
      company: 'VisionLabs',
      title: 'Engenheiro de Visão Computacional',
      description: 'Vaga remota Python + OpenCV. Link nos comentários.',
      emails: [],
      matched_keywords: ['Python'],
      match_score: 70,
      url: 'https://www.linkedin.com/feed/update/urn:li:activity:7600000000000000901/',
      created_at: new Date().toISOString(),
    };
    const evaluatedPost: RecruiterPost = {
      ...importedPost,
      ai_classification: 'vaga_ativa',
      ai_score: 84,
      ai_verdict: 'Strong Fit',
      ai_summary: 'Alta aderência em Python, OpenCV e Visão Computacional.',
      ai_model: 'gemini-test',
      ai_evaluated_at: new Date().toISOString(),
      ai_details: {
        subscores: { technical: 88, experience: 82, behavioral: 80, career: 84 },
        strengths: ['Experiência em Visão Computacional'],
        gaps: ['Validar deploy em edge'],
      },
    };

    apiSpy.pasteRecruiterPost.and.returnValue(of({ ok: true, post: importedPost }));
    apiSpy.triageRecruiterPosts.and.returnValue(
      of({
        ok: true,
        triaged: 1,
        active_jobs: 1,
        talent_pools_discarded: 0,
        not_a_job: 0,
        errors: 0,
        posts: [evaluatedPost],
      })
    );

    const interestedEmitted: RecruiterPost[] = [];
    const dismissedEmitted: number[] = [];
    component.postInterested.subscribe(p => interestedEmitted.push(p));
    component.postDismissed.subscribe(id => dismissedEmitted.push(id));

    component.togglePastePanel();
    component.pasteText.set(importedPost.description);
    component.pasteUrl.set(importedPost.url!);
    component.submitManualPaste();
    fixture.detectChanges();

    expect(apiSpy.pasteRecruiterPost).toHaveBeenCalledWith({
      raw_text: importedPost.description,
      url: importedPost.url,
      allow_without_email: true,
    });
    expect(apiSpy.triageRecruiterPosts).toHaveBeenCalledWith({ post_ids: [901], limit: 5 });
    expect(component.showPastePanel()).toBeTrue();
    expect(component.pastedReviews().length).toBe(1);

    const el: HTMLElement = fixture.nativeElement;
    expect(el.textContent).toContain('84/100');
    expect(el.textContent).toContain('Strong Fit');
    expect(el.textContent).toContain('Alta aderência em Python, OpenCV e Visão Computacional.');
    expect(el.textContent).toContain('Experiência em Visão Computacional');
    expect(el.textContent).toContain('Validar deploy em edge');

    // Ação direta: Me interessa
    component.saveReviewAsInterested(component.pastedReviews()[0]);
    fixture.detectChanges();
    expect(apiSpy.markRecruiterPostInterested).toHaveBeenCalledWith(901);
    expect(component.pastedReviews()[0].decision).toBe('interested');
    expect(interestedEmitted.length).toBe(1);

    // Ação direta: Descartar remove o card inline
    component.discardReview(component.pastedReviews()[0]);
    fixture.detectChanges();
    expect(apiSpy.dismissRecruiterPost).toHaveBeenCalledWith(901);
    expect(component.pastedReviews().length).toBe(0);
    expect(dismissedEmitted).toEqual([901]);
  });

  it('keeps pasted card visible with retry and decision buttons when AI triage returns an error', () => {
    const importedPost: RecruiterPost = {
      id: 902,
      portal: 'linkedin_post',
      company: 'Acme',
      title: 'Dev Python',
      description: 'Vaga Python remoto para time de IA.',
      emails: ['rh@acme.dev'],
      matched_keywords: ['Python'],
      match_score: 60,
      created_at: new Date().toISOString(),
    };
    apiSpy.pasteRecruiterPost.and.returnValue(of({ ok: true, post: importedPost }));
    apiSpy.triageRecruiterPosts.and.returnValue(
      throwError(() => ({ error: { detail: 'Consentimento de IA necessário.' } }))
    );

    component.togglePastePanel();
    component.pasteText.set(importedPost.description);
    component.submitManualPaste();
    fixture.detectChanges();

    expect(component.showPastePanel()).toBeTrue();
    expect(component.pastedReviews().length).toBe(1);
    expect(component.pastedReviews()[0].evalError).toContain('Consentimento de IA');
    const el: HTMLElement = fixture.nativeElement;
    expect(el.textContent).toContain('Tentar avaliar novamente');
    expect(el.textContent).toContain('Me interessa');
    expect(el.textContent).toContain('Descartar');
  });

  it('emits pasteError cleanly when manual paste endpoint fails', () => {
    const errors: string[] = [];
    component.pasteError.subscribe(msg => errors.push(msg));
    apiSpy.pasteRecruiterPost.and.returnValue(
      throwError(() => ({ error: { detail: 'Nenhum e-mail encontrado.' } }))
    );

    component.togglePastePanel();
    component.pasteText.set('Texto sem email');
    component.submitManualPaste();

    expect(component.submittingPaste()).toBeFalse();
    expect(errors).toEqual(['Nenhum e-mail encontrado.']);
  });
});
