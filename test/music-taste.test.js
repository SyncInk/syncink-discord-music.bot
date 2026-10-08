'use strict';

const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const test = require('node:test');
const { MusicTaste } = require('../taste');

function createTaste(t, options = {}) {
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'syncink-taste-'));
  t.after(() => fs.rmSync(directory, { recursive: true, force: true }));
  return new MusicTaste({
    filePath: path.join(directory, 'taste.json'),
    logger: { warn() {} },
    ...options,
  });
}

const playedTrack = { title: 'Blue in Green', cleanTitle: 'Blue in Green', author: 'Miles Davis', url: 'track:played' };
const candidateMiles = { title: 'So What', author: 'Miles Davis', url: 'track:miles' };
const candidateOther = { title: 'Dreams', author: 'Fleetwood Mac', url: 'track:other' };

test('taste learning is off until a user opts in', (t) => {
  const taste = createTaste(t);
  assert.equal(taste.recordTrack('guild-a', 'user-a', playedTrack), false);
  assert.equal(taste.getProfile('guild-a', 'user-a'), null);
});

test('opted-in likes build a local profile and rank similar artists', async (t) => {
  const taste = createTaste(t);
  taste.setEnabled('guild-a', 'user-a', true);
  assert.equal(taste.recordTrack('guild-a', 'user-a', playedTrack, 3, 'like'), true);

  const selected = await taste.chooseAutoplay({
    guildId: 'guild-a',
    userId: 'user-a',
    currentTrack: playedTrack,
    candidates: [candidateOther, candidateMiles],
    historyUrls: [playedTrack.url],
    allowAI: false,
  });
  assert.equal(selected, candidateMiles);
});

test('opt-out disables AI and forget removes saved taste', async (t) => {
  let apiCalls = 0;
  const taste = createTaste(t, {
    apiKey: 'test-key',
    fetchImpl: async () => {
      apiCalls += 1;
      return { ok: true, json: async () => ({ output_text: '{"choice":0}' }) };
    },
  });
  taste.setEnabled('guild-a', 'user-a', true);
  taste.recordTrack('guild-a', 'user-a', playedTrack, 3, 'like');
  taste.setEnabled('guild-a', 'user-a', false);

  const selected = await taste.chooseAutoplay({
    guildId: 'guild-a',
    userId: 'user-a',
    currentTrack: playedTrack,
    candidates: [candidateMiles, candidateOther],
    allowAI: true,
  });
  assert.equal(apiCalls, 0);
  assert.ok(selected);
  assert.equal(taste.forget('guild-a', 'user-a'), true);
  assert.equal(taste.getProfile('guild-a', 'user-a'), null);
});

test('AI selects a fresh candidate and excludes previously played tracks', async (t) => {
  const taste = createTaste(t, {
    apiKey: 'test-key',
    fetchImpl: async (_url, request) => {
      const body = JSON.parse(request.body);
      assert.equal(body.store, false);
      assert.doesNotMatch(body.input, /user-a|guild-a/);
      return { ok: true, json: async () => ({ output_text: '{"choice":0}' }) };
    },
  });
  taste.setEnabled('guild-a', 'user-a', true);
  taste.recordTrack('guild-a', 'user-a', playedTrack, 3, 'like');

  const selected = await taste.chooseAutoplay({
    guildId: 'guild-a',
    userId: 'user-a',
    currentTrack: playedTrack,
    candidates: [candidateOther, candidateMiles],
    historyUrls: [candidateOther.url],
  });
  assert.equal(selected, candidateMiles);
});
