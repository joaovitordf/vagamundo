import {
  HttpContextToken,
  HttpErrorResponse,
  HttpInterceptorFn,
} from '@angular/common/http';
import { inject } from '@angular/core';
import { catchError, switchMap, throwError } from 'rxjs';
import { CsrfTokenService } from '../services/csrf-token.service';

const CSRF_RETRIED = new HttpContextToken<boolean>(() => false);
const SAFE_METHODS = new Set(['GET', 'HEAD', 'OPTIONS']);

function extractPathname(url: string): string {
  if (url.startsWith('http://') || url.startsWith('https://')) {
    try {
      return new URL(url).pathname;
    } catch {
      return url;
    }
  }
  return url.split('?')[0];
}

function isProtectedMutation(method: string, url: string): boolean {
  if (SAFE_METHODS.has(method.toUpperCase())) {
    return false;
  }
  const pathname = extractPathname(url);
  return pathname.startsWith('/api/') && pathname !== '/api/token';
}

export const authTokenInterceptor: HttpInterceptorFn = (req, next) => {
  if (!isProtectedMutation(req.method, req.url)) {
    return next(req);
  }

  const csrf = inject(CsrfTokenService);

  return csrf.ensureToken().pipe(
    switchMap((token) => {
      const authedReq = token
        ? req.clone({ setHeaders: { 'X-Painel-Token': token } })
        : req;
      return next(authedReq);
    }),
    catchError((err: unknown) => {
      if (
        err instanceof HttpErrorResponse &&
        err.status === 403 &&
        !req.context.get(CSRF_RETRIED)
      ) {
        return csrf.refreshToken().pipe(
          switchMap((freshToken) => {
            const retriedReq = req.clone({
              context: req.context.set(CSRF_RETRIED, true),
              setHeaders: freshToken ? { 'X-Painel-Token': freshToken } : {},
            });
            return next(retriedReq);
          })
        );
      }
      return throwError(() => err);
    })
  );
};
