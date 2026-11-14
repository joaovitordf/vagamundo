import { TestBed } from '@angular/core/testing';
import { HttpClient, provideHttpClient, withInterceptors } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { firstValueFrom, forkJoin } from 'rxjs';
import { authTokenInterceptor } from './auth-token.interceptor';
import { CsrfTokenService } from '../services/csrf-token.service';

describe('authTokenInterceptor & CsrfTokenService', () => {
  let http: HttpClient;
  let httpMock: HttpTestingController;
  let csrfService: CsrfTokenService;

  beforeEach(() => {
    TestBed.configureTestingModule({
      providers: [
        provideHttpClient(withInterceptors([authTokenInterceptor])),
        provideHttpClientTesting(),
      ],
    });
    http = TestBed.inject(HttpClient);
    httpMock = TestBed.inject(HttpTestingController);
    csrfService = TestBed.inject(CsrfTokenService);
    csrfService.clearToken();
  });

  afterEach(() => {
    httpMock.verify();
  });

  it('does not request CSRF token for GET requests', async () => {
    const promise = firstValueFrom(http.get<{ ok: boolean }>('/api/saved'));
    const req = httpMock.expectOne('/api/saved');
    expect(req.request.headers.has('X-Painel-Token')).toBeFalse();
    req.flush({ ok: true });
    expect(await promise).toEqual({ ok: true });
  });

  it('fetches token once for concurrent POST mutations and attaches X-Painel-Token', async () => {
    const promise = firstValueFrom(
      forkJoin([
        http.post('/api/discard', { url: 'u1' }),
        http.post('/api/restore', { url: 'u2' }),
      ])
    );

    const tokenReq = httpMock.expectOne('/api/token');
    expect(tokenReq.request.method).toBe('GET');
    tokenReq.flush({ token: 'tok-abc' });

    const req1 = httpMock.expectOne('/api/discard');
    const req2 = httpMock.expectOne('/api/restore');
    expect(req1.request.headers.get('X-Painel-Token')).toBe('tok-abc');
    expect(req2.request.headers.get('X-Painel-Token')).toBe('tok-abc');

    req1.flush({ ok: true });
    req2.flush({ ok: true });
    await promise;
  });

  it('refreshes CSRF token and retries once on HTTP 403 for DELETE and POST', async () => {
    const seedPromise = firstValueFrom(http.post('/api/mark', { urls: [] }));
    httpMock.expectOne('/api/token').flush({ token: 'stale-tok' });
    const seedPost = httpMock.expectOne('/api/mark');
    seedPost.flush({ ok: true });
    await seedPromise;

    const delPromise = firstValueFrom(http.delete<{ deleted: boolean }>('/api/applications/event/99'));

    const firstAttempt = httpMock.expectOne('/api/applications/event/99');
    expect(firstAttempt.request.method).toBe('DELETE');
    expect(firstAttempt.request.headers.get('X-Painel-Token')).toBe('stale-tok');
    firstAttempt.flush({ detail: 'expired' }, { status: 403, statusText: 'Forbidden' });

    const refreshReq = httpMock.expectOne('/api/token');
    refreshReq.flush({ token: 'fresh-tok' });

    const retryAttempt = httpMock.expectOne('/api/applications/event/99');
    expect(retryAttempt.request.method).toBe('DELETE');
    expect(retryAttempt.request.headers.get('X-Painel-Token')).toBe('fresh-tok');
    retryAttempt.flush({ deleted: true });

    expect(await delPromise).toEqual({ deleted: true });
  });
});
