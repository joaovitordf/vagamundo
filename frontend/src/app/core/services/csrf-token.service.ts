import { DOCUMENT } from '@angular/common';
import { HttpBackend, HttpClient } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable, of } from 'rxjs';
import { catchError, finalize, map, shareReplay, tap } from 'rxjs/operators';

@Injectable({
  providedIn: 'root',
})
export class CsrfTokenService {
  private readonly document = inject(DOCUMENT);
  private readonly rawHttp = new HttpClient(inject(HttpBackend));

  private token = '';
  private inFlightRefresh$: Observable<string> | null = null;

  constructor() {
    this.token = this.readMetaToken();
  }

  private readMetaToken(): string {
    const meta = this.document.querySelector('meta[name="painel-token"]') as HTMLMetaElement | null;
    const content = meta?.content?.trim() ?? '';
    return content && content !== '__PAINEL_TOKEN__' ? content : '';
  }

  getToken(): string {
    if (!this.token) {
      this.token = this.readMetaToken();
    }
    return this.token;
  }

  ensureToken(): Observable<string> {
    const current = this.getToken();
    return current ? of(current) : this.refreshToken();
  }

  refreshToken(): Observable<string> {
    if (!this.inFlightRefresh$) {
      this.inFlightRefresh$ = this.rawHttp.get<{ token?: string }>('/api/token').pipe(
        map((res) => res?.token ?? ''),
        tap((token) => {
          this.token = token;
        }),
        catchError(() => of('')),
        finalize(() => {
          this.inFlightRefresh$ = null;
        }),
        shareReplay(1)
      );
    }
    return this.inFlightRefresh$;
  }

  /** @internal Test helper to reset cached token state between unit specs. */
  clearToken(): void {
    this.token = '';
    this.inFlightRefresh$ = null;
  }
}
