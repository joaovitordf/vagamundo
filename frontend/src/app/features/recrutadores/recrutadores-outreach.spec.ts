import { RecruiterPost } from '../../core/models/vaga.model';
import { removePostAndFlagEmail } from './recrutadores.component';
import {
  filterApplicationsList,
  isDirectEmailApplication,
} from '../candidaturas/candidaturas.component';

describe('Recruiter outreach history helpers', () => {
  it('removes contacted post and immediately flags sibling posts sharing the email', () => {
    const posts: RecruiterPost[] = [
      {
        id: 1,
        emails: ['arturo.gutierrez@ibertech.org'],
        title: 'Fullstack Angular / Java',
        company: 'Ibertech',
        portal: 'freehire-search',
        description: 'Vaga 1',
        matched_keywords: ['Angular'],
        match_score: 90,
        created_at: '2026-11-10T10:00:00',
      },
      {
        id: 2,
        emails: ['rh@ibertech.org', 'ARTURO.GUTIERREZ@ibertech.org'],
        title: 'Tech Lead Java',
        company: 'Ibertech Latam',
        portal: 'linkedin_post',
        description: 'Vaga 2',
        matched_keywords: ['Java'],
        match_score: 80,
        created_at: '2026-11-11T10:00:00',
      },
      {
        id: 3,
        emails: ['jobs@outra.io'],
        title: 'Backend Go',
        company: 'Outra Corp',
        portal: 'hn-search',
        description: 'Vaga 3',
        matched_keywords: [],
        match_score: 50,
        created_at: '2026-11-11T11:00:00',
      },
    ];

    const next = removePostAndFlagEmail(posts, 1, 'arturo.gutierrez@ibertech.org', {
      company: 'Ibertech',
      title: 'Fullstack Angular / Java',
      contacted_at: '2026-11-11',
    });

    expect(next.map(p => p.id)).toEqual([2, 3]);
    expect(next[0].previously_contacted?.length).toBe(1);
    expect(next[0].previously_contacted?.[0].email).toBe('arturo.gutierrez@ibertech.org');
    expect(next[0].previously_contacted?.[0].company).toBe('Ibertech');
    expect(next[1].previously_contacted).toBeUndefined();
  });

  it('filters applications by direct email channel and recruiter email text search', () => {
    const apps = [
      {
        id: 10,
        company: 'Ibertech',
        role: 'Fullstack Angular',
        channel: 'freehire-search',
        portal: 'freehire-search',
        contact_channel: 'recruiter_email',
        contacted_email: 'arturo.gutierrez@ibertech.org',
        recruiter_emails: ['arturo.gutierrez@ibertech.org'],
        status: 'applied',
        applied_date: '2026-11-11',
      },
      {
        id: 11,
        company: 'Acme Portal',
        role: 'Engenheiro de Software',
        channel: 'gupy-search',
        portal: 'gupy-search',
        contact_channel: 'portal',
        url: 'https://acme.gupy.io/jobs/123',
        status: 'applied',
        applied_date: '2026-11-10',
      },
    ];

    expect(isDirectEmailApplication(apps[0])).toBeTrue();
    expect(isDirectEmailApplication(apps[1])).toBeFalse();

    const baseOpts = {
      searchTerm: '',
      statusFilter: 'all',
      channelFilter: 'recruiter_email' as const,
      dateCriterion: 'applied' as const,
      dateRange: 'all',
      customStartDate: '',
      customEndDate: '',
      sortOrder: 'recent' as const,
    };

    const directOnly = filterApplicationsList(apps, baseOpts);
    expect(directOnly.map(a => a.id)).toEqual([10]);

    const portalOnly = filterApplicationsList(apps, { ...baseOpts, channelFilter: 'portal' });
    expect(portalOnly.map(a => a.id)).toEqual([11]);

    const byEmailSearch = filterApplicationsList(apps, {
      ...baseOpts,
      channelFilter: 'all',
      searchTerm: 'arturo.gutierrez',
    });
    expect(byEmailSearch.map(a => a.id)).toEqual([10]);
  });
});
