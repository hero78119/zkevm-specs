import pytest

from zkevm_specs.evm import (
    ExecutionState,
    StepState,
    verify_steps,
    Tables,
    Block,
    Bytecode,
    RWDictionary,
)
from zkevm_specs.util import rand_fq, RLC, N_BYTES_WORD

TESTING_DATA = [i for i in range(0, 7)]


@pytest.mark.parametrize("memory_word_size", TESTING_DATA)
def test_msize(memory_word_size: int):
    randomness = rand_fq()

    value = memory_word_size * N_BYTES_WORD
    value = RLC(value, randomness)

    bytecode = Bytecode().msize().stop()
    bytecode_hash = RLC(bytecode.hash(), randomness)

    tables = Tables(
        block_table=set(Block().table_assignments(randomness)),
        tx_table=set(),
        bytecode_table=set(bytecode.table_assignments(randomness)),
        rw_table=set(RWDictionary(9).stack_write(1, 1022, value).rws),
    )

    verify_steps(
        randomness=randomness,
        tables=tables,
        steps=[
            StepState(
                execution_state=ExecutionState.MSIZE,
                rw_counter=9,
                call_id=1,
                is_root=True,
                is_create=False,
                code_hash=bytecode_hash,
                program_counter=0,
                stack_pointer=1023,
                memory_word_size=memory_word_size,
                gas_left=2,
            ),
            StepState(
                execution_state=ExecutionState.STOP,
                rw_counter=10,
                call_id=1,
                is_root=True,
                is_create=False,
                code_hash=bytecode_hash,
                program_counter=1,
                stack_pointer=1022,
                memory_word_size=memory_word_size,
                gas_left=0,
            ),
        ],
    )
