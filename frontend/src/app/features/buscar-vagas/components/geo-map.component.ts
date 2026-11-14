import {
  AfterViewInit,
  ChangeDetectionStrategy,
  ChangeDetectorRef,
  Component,
  ElementRef,
  EventEmitter,
  Input,
  OnChanges,
  Output,
  ViewChild,
  inject,
} from '@angular/core';
import { Vaga } from '../../../core/models/vaga.model';
import { ActiveGeoFilter, resolveGeo } from '../../../core/utils/job-filters.util';

const SVG_NS = 'http://www.w3.org/2000/svg';

interface GeoMapAggregates {
  brCounts: Record<string, number>;
  worldCounts: Record<string, number>;
  brScores: Record<string, number>;
  worldScores: Record<string, number>;
}

@Component({
  selector: 'app-geo-map',
  standalone: true,
  imports: [],
  templateUrl: './geo-map.component.html',
  styleUrl: './geo-map.component.css',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class GeoMapComponent implements AfterViewInit, OnChanges {
  private readonly cdr = inject(ChangeDetectorRef);

  @ViewChild('mapWorldContainer') mapWorldContainer!: ElementRef<HTMLDivElement>;
  @ViewChild('mapBrasilContainer') mapBrasilContainer!: ElementRef<HTMLDivElement>;

  @Input() baseVagas: Vaga[] = [];
  @Input() geoData: any = null;
  @Input() mapMode: 'world' | 'brasil' = 'world';
  @Input() activeGeoFilter: ActiveGeoFilter | null = null;
  @Input() isTriageMode = false;
  @Input() hasTriagedJobs = false;
  @Input() indicatorText = 'Todas as localidades';

  @Output() mapModeChange = new EventEmitter<'world' | 'brasil'>();
  @Output() geoFilterChange = new EventEmitter<ActiveGeoFilter | null>();
  @Output() triageModeToggle = new EventEmitter<void>();

  remoteCounts: Record<string, number> = { REMOTO_BR: 0, EU_REMOTE: 0, GLOBAL_REMOTE: 0 };

  private viewInitialized = false;
  private lastAggregates: GeoMapAggregates = {
    brCounts: {},
    worldCounts: {},
    brScores: {},
    worldScores: {},
  };

  ngOnChanges(): void {
    this.recomputeCounts();
    if (this.viewInitialized) {
      this.renderMaps();
    }
  }

  ngAfterViewInit(): void {
    this.viewInitialized = true;
    this.renderMaps();
  }

  selectRemoteChip(code: string, name: string): void {
    if (this.activeGeoFilter?.type === 'remote' && this.activeGeoFilter.code === code) {
      this.geoFilterChange.emit(null);
    } else {
      const cnt = this.remoteCounts[code] || 0;
      this.geoFilterChange.emit({ type: 'remote', code, name, count: cnt });
    }
  }

  private recomputeCounts(): void {
    const brCounts: Record<string, number> = {};
    const worldCounts: Record<string, number> = {};
    const brScores: Record<string, number> = {};
    const worldScores: Record<string, number> = {};
    const nextRemoteCounts: Record<string, number> = { REMOTO_BR: 0, EU_REMOTE: 0, GLOBAL_REMOTE: 0 };

    for (const r of this.baseVagas || []) {
      const geo = resolveGeo(r);
      const score = r.screening && typeof r.screening.score === 'number' ? r.screening.score : -1;

      if (geo.remoteBucket) {
        nextRemoteCounts[geo.remoteBucket] = (nextRemoteCounts[geo.remoteBucket] || 0) + 1;
      }

      if (geo.countryCode === 'BR') {
        worldCounts['BR'] = (worldCounts['BR'] || 0) + 1;
        if (score > (worldScores['BR'] || -1)) worldScores['BR'] = score;
        if (geo.code && geo.code !== 'REMOTO_BR') {
          brCounts[geo.code] = (brCounts[geo.code] || 0) + 1;
          if (score > (brScores[geo.code] || -1)) brScores[geo.code] = score;
        }
      } else if (geo.countryCode && geo.countryCode !== 'GLOBAL_REMOTE' && geo.countryCode !== 'EU_REMOTE') {
        worldCounts[geo.countryCode] = (worldCounts[geo.countryCode] || 0) + 1;
        if (score > (worldScores[geo.countryCode] || -1)) worldScores[geo.countryCode] = score;
      }
    }

    this.remoteCounts = nextRemoteCounts;
    this.lastAggregates = { brCounts, worldCounts, brScores, worldScores };
  }

  private renderMaps(): void {
    if (!this.geoData) return;

    if (this.mapWorldContainer?.nativeElement) {
      this.renderWorldMapSvg(
        this.geoData.world || {},
        this.lastAggregates.worldCounts,
        this.lastAggregates.worldScores
      );
    }
    if (this.mapBrasilContainer?.nativeElement) {
      this.renderBrasilMapSvg(
        this.geoData.brasil || {},
        this.lastAggregates.brCounts,
        this.lastAggregates.brScores
      );
    }
  }

  private createSvgEl(tag: string, attrs: Record<string, string | number>, text?: string): SVGElement {
    const node = document.createElementNS(SVG_NS, tag);
    for (const [key, val] of Object.entries(attrs)) {
      node.setAttribute(key, String(val));
    }
    if (text !== undefined) {
      node.textContent = text;
    }
    return node;
  }

  private appendOceanGradient(svg: SVGElement, id: string, cx: string, cy: string): void {
    const defs = document.createElementNS(SVG_NS, 'defs');
    const grad = this.createSvgEl('radialGradient', { id, cx, cy, r: '70%' });
    grad.appendChild(this.createSvgEl('stop', { offset: '0%', 'stop-color': '#0d1525' }));
    grad.appendChild(this.createSvgEl('stop', { offset: '100%', 'stop-color': '#070b13' }));
    defs.appendChild(grad);
    svg.appendChild(defs);
  }

  private createMapBadge(
    code: string,
    cx: number,
    cy: number,
    cnt: number,
    maxScore: number,
    isHighFit: boolean
  ): SVGElement {
    const gBadge = this.createSvgEl('g', { style: 'cursor: pointer;' });
    const hasScore = this.isTriageMode && maxScore >= 0;
    const rectW = hasScore ? 62 : 46;

    gBadge.appendChild(
      this.createSvgEl('rect', {
        class: `geo-badge-bg ${isHighFit ? 'fit-high' : ''}`.trim(),
        x: cx - rectW / 2,
        y: cy - 12,
        width: rectW,
        height: 24,
      })
    );
    gBadge.appendChild(this.createSvgEl('text', { class: 'geo-badge', x: cx, y: cy - 1 }, code));
    gBadge.appendChild(
      this.createSvgEl(
        'text',
        {
          class: 'geo-badge-sub',
          style: `fill: ${isHighFit ? '#34d399' : '#38bdf8'}; font-size: 8.5px;`,
          x: cx,
          y: cy + 9,
        },
        hasScore ? `${cnt} (${maxScore}p)` : `${cnt} vaga(s)`
      )
    );
    return gBadge;
  }

  private renderWorldMapSvg(
    world: Record<string, any>,
    counts: Record<string, number>,
    scores: Record<string, number>
  ): void {
    const el = this.mapWorldContainer.nativeElement;
    el.replaceChildren();

    const svg = this.createSvgEl('svg', {
      viewBox: '0 0 1000 500',
      style: 'width: 100%; height: auto; max-height: 500px; display: block;',
    });

    this.appendOceanGradient(svg, 'world-ocean-grad', '50%', '45%');

    svg.appendChild(
      this.createSvgEl('rect', {
        width: 1000,
        height: 500,
        rx: 10,
        fill: 'url(#world-ocean-grad)',
      })
    );

    const gGrid = this.createSvgEl('g', { style: 'pointer-events: none;' });
    const gridLines: Array<Record<string, string | number>> = [
      { x1: 20, y1: 250, x2: 980, y2: 250, stroke: 'rgba(51, 65, 85, 0.28)', 'stroke-dasharray': '4 6' },
      { x1: 20, y1: 180, x2: 980, y2: 180, stroke: 'rgba(51, 65, 85, 0.16)', 'stroke-dasharray': '3 6' },
      { x1: 20, y1: 320, x2: 980, y2: 320, stroke: 'rgba(51, 65, 85, 0.16)', 'stroke-dasharray': '3 6' },
      { x1: 250, y1: 20, x2: 250, y2: 480, stroke: 'rgba(51, 65, 85, 0.16)', 'stroke-dasharray': '3 6' },
      { x1: 500, y1: 20, x2: 500, y2: 480, stroke: 'rgba(51, 65, 85, 0.22)', 'stroke-dasharray': '4 6' },
      { x1: 750, y1: 20, x2: 750, y2: 480, stroke: 'rgba(51, 65, 85, 0.16)', 'stroke-dasharray': '3 6' },
    ];
    for (const attrs of gridLines) {
      gGrid.appendChild(this.createSvgEl('line', attrs));
    }
    svg.appendChild(gGrid);

    const gPaths = document.createElementNS(SVG_NS, 'g');
    const gBadges = document.createElementNS(SVG_NS, 'g');

    for (const [code, info] of Object.entries(world)) {
      if (code === 'AQ') continue;
      const cnt = counts[code] || 0;
      const maxScore = scores[code] || -1;
      const isHighFit = this.isTriageMode && maxScore >= 75;
      const isActive = this.activeGeoFilter?.type === 'country' && this.activeGeoFilter.code === code;
      const fill = this.getGeoColor(cnt, maxScore, isActive);

      const path = this.createSvgEl('path', {
        class: `geo-state ${isActive ? 'active' : ''} ${isHighFit ? 'fit-high' : ''}`.trim(),
        d: info.path,
        fill,
        'data-code': code,
        'data-name': info.name,
      });

      const selectCountry = () => {
        if (code === 'BR') {
          this.mapModeChange.emit('brasil');
        } else if (this.activeGeoFilter?.type === 'country' && this.activeGeoFilter.code === code) {
          this.geoFilterChange.emit(null);
        } else {
          this.geoFilterChange.emit({ type: 'country', code, name: `${info.name} (${code})`, count: cnt });
        }
        this.cdr.markForCheck();
      };

      path.addEventListener('click', selectCountry);
      gPaths.appendChild(path);

      if (cnt > 0 && info.cx > 0 && info.cy > 0) {
        const gBadge = this.createMapBadge(code, info.cx, info.cy, cnt, maxScore, isHighFit);
        gBadge.addEventListener('click', selectCountry);
        gBadges.appendChild(gBadge);
      }
    }

    svg.appendChild(gPaths);
    svg.appendChild(gBadges);
    el.appendChild(svg);
  }

  private renderBrasilMapSvg(
    states: Record<string, any>,
    counts: Record<string, number>,
    scores: Record<string, number>
  ): void {
    const el = this.mapBrasilContainer.nativeElement;
    el.replaceChildren();

    const svg = this.createSvgEl('svg', {
      viewBox: '0 0 600 600',
      style: 'width: 100%; height: auto; max-height: 500px; display: block;',
    });

    this.appendOceanGradient(svg, 'br-ocean-grad', '50%', '50%');

    svg.appendChild(
      this.createSvgEl('rect', {
        width: 600,
        height: 600,
        rx: 10,
        fill: 'url(#br-ocean-grad)',
      })
    );

    const gPaths = document.createElementNS(SVG_NS, 'g');
    const gBadges = document.createElementNS(SVG_NS, 'g');

    for (const [uf, info] of Object.entries(states)) {
      const cnt = counts[uf] || 0;
      const maxScore = scores[uf] || -1;
      const isHighFit = this.isTriageMode && maxScore >= 75;
      const isActive = this.activeGeoFilter?.type === 'uf' && this.activeGeoFilter.code === uf;
      const fill = this.getGeoColor(cnt, maxScore, isActive);

      const path = this.createSvgEl('path', {
        class: `geo-state ${isActive ? 'active' : ''} ${isHighFit ? 'fit-high' : ''}`.trim(),
        d: info.path,
        fill,
        'data-uf': uf,
        'data-name': info.name,
      });

      const selectUf = () => {
        if (this.activeGeoFilter?.type === 'uf' && this.activeGeoFilter.code === uf) {
          this.geoFilterChange.emit(null);
        } else {
          this.geoFilterChange.emit({ type: 'uf', code: uf, name: `${info.name} (${uf})`, count: cnt });
        }
        this.cdr.markForCheck();
      };

      path.addEventListener('click', selectUf);
      gPaths.appendChild(path);

      if (cnt > 0) {
        const gBadge = this.createMapBadge(uf, info.cx, info.cy, cnt, maxScore, isHighFit);
        gBadge.addEventListener('click', selectUf);
        gBadges.appendChild(gBadge);
      } else {
        gBadges.appendChild(
          this.createSvgEl(
            'text',
            {
              class: 'geo-badge-sub',
              style: 'fill: #475569; font-size: 8px;',
              x: info.cx,
              y: info.cy + 3,
            },
            uf
          )
        );
      }
    }

    svg.appendChild(gPaths);
    svg.appendChild(gBadges);
    el.appendChild(svg);
  }

  private getGeoColor(cnt: number, maxScore: number, isActive: boolean): string {
    if (isActive) return '#38bdf8';
    if (!cnt || cnt <= 0) return '#131b2b';
    if (this.isTriageMode) {
      if (maxScore >= 75) return '#10b981';
      if (maxScore >= 60) return '#0ea5e9';
      return '#64748b';
    }
    if (cnt >= 10) return '#f59e0b';
    if (cnt >= 5) return '#0284c7';
    return '#0369a1';
  }
}
