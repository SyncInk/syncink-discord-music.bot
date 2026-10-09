'use strict';

const assert = require('node:assert/strict');
const test = require('node:test');
const {
  canonicalSongKey,
  isUnrequestedVariant,
  matchConfidence,
  prioritizeTracksForPlayback,
} = require('../track-matching');

test('ranks close artist and title matches ahead of unrelated results', () => {
  const tracks = [
    { title: 'Random reaction to the song', author: 'Listener', url: 'https://example.com/reaction', durationMS: 180_000, source: 'youtube' },
    { title: 'Night Drive', author: 'Nova', url: 'https://example.com/song', durationMS: 180_000, source: 'youtube' },
    { title: 'Completely unrelated', author: 'Other', url: 'https://example.com/unrelated', durationMS: 180_000, source: 'youtube' },
  ];
  const ranked = prioritizeTracksForPlayback(tracks, 'Nova Night Drive');
  assert.equal(ranked[0].url, 'https://example.com/song');
  assert.equal(ranked.some((track) => track.url.endsWith('/unrelated')), false);
});

test('filters obvious variants unless the user requested that variant', () => {
  const edit = { title: 'Night Drive slowed + reverb', url: 'https://example.com/edit', durationMS: 180_000 };
  const short = { title: 'Night Drive', url: 'https://youtube.com/shorts/abc', durationMS: 30_000 };
  assert.equal(isUnrequestedVariant(edit, 'Night Drive'), true);
  assert.equal(isUnrequestedVariant(edit, 'Night Drive slowed reverb'), false);
  assert.equal(isUnrequestedVariant(short, 'Night Drive'), true);
});

test('exact provider URLs preserve requested playback even for short variants', () => {
  const track = { title: 'Night Drive Shorts Edit', url: 'https://youtube.com/watch?v=abc', durationMS: 30_000 };
  assert.equal(isUnrequestedVariant(track, track.url), false);
  assert.equal(matchConfidence(track, track.url), 1);
  assert.equal(prioritizeTracksForPlayback([track], track.url).length, 1);
});

test('autoplay identity removes upload suffixes and search keeps distinct artists', () => {
  const original = { title: 'Night Drive (Official Audio)', author: 'Nova - Topic', url: 'https://example.com/a', durationMS: 201_000 };
  const mirror = { title: 'Night Drive', author: 'Nova', url: 'https://example.com/b', durationMS: 201_000 };
  const otherArtist = { title: 'Night Drive', author: 'The Comets', url: 'https://example.com/c', durationMS: 201_000 };
  assert.equal(canonicalSongKey(original), canonicalSongKey(mirror));
  const ranked = prioritizeTracksForPlayback([original, mirror, otherArtist], 'Night Drive');
  assert.equal(ranked.length, 2);
  assert.equal(ranked.some((track) => track.author === 'The Comets'), true);
});
